"""Bounded, event-driven BlueZ controls with an explicit-confirmation pairing agent."""
import os
import sys
import threading
from qt_compat import QObject, Property, Signal, Slot

BLUEZ = 'org.bluez'
ADAPTER = BLUEZ + '.Adapter1'
DEVICE = BLUEZ + '.Device1'
BATTERY = BLUEZ + '.Battery1'
AGENT = BLUEZ + '.Agent1'
MANAGER = BLUEZ + '.AgentManager1'
PROPERTIES = 'org.freedesktop.DBus.Properties'
OBJECTS = 'org.freedesktop.DBus.ObjectManager'
EMPTY = dict(available=False, powered=False, discovering=False, busy=False, status='Bluetooth unavailable')
AGENT_XML = '''<node><interface name="org.bluez.Agent1">
<method name="Release"/>
<method name="RequestPinCode"><arg type="o" direction="in"/><arg type="s" direction="out"/></method>
<method name="DisplayPinCode"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
<method name="RequestPasskey"><arg type="o" direction="in"/><arg type="u" direction="out"/></method>
<method name="DisplayPasskey"><arg type="o" direction="in"/><arg type="u" direction="in"/><arg type="q" direction="in"/></method>
<method name="RequestConfirmation"><arg type="o" direction="in"/><arg type="u" direction="in"/></method>
<method name="RequestAuthorization"><arg type="o" direction="in"/></method>
<method name="AuthorizeService"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
<method name="Cancel"/>
</interface></node>'''


def plain(value, limit=200):
    return ' '.join(str(value).split())[:limit]


def inventory(objects, busy=False, status=''):
    """Only retain bounded, typed display fields from BlueZ's object inventory."""
    adapters = [(path, interfaces[ADAPTER]) for path, interfaces in objects.items() if ADAPTER in interfaces]
    adapters.sort(key=lambda row: (not bool(row[1].get('Powered')), row[0]))
    adapter_path, adapter = adapters[0] if adapters else ('', {})
    adapter_paths = {path for path, _ in adapters}
    devices = []
    for path, interfaces in objects.items():
        values = interfaces.get(DEVICE)
        if values is None or (values.get('Adapter') and values['Adapter'] not in adapter_paths):
            continue
        percentage = interfaces.get(BATTERY, {}).get('Percentage')
        battery_present = type(percentage) is int and 0 <= percentage <= 100
        devices.append(dict(path=path, name=plain(values.get('Alias') or values.get('Name') or values.get('Address') or 'Bluetooth device'), paired=values.get('Paired') is True, connected=values.get('Connected') is True, trusted=values.get('Trusted') is True, batteryPresent=battery_present, batteryPercent=percentage if battery_present else 0))
    devices.sort(key=lambda row: (not row['connected'], not row['paired'], row['name'].casefold(), row['path']))
    powered = adapter.get('Powered') is True
    discovering = any(row.get('Discovering') is True for _, row in adapters)
    state = dict(available=bool(adapters), powered=powered, discovering=discovering, busy=bool(busy), status=plain(status or ('Bluetooth unavailable' if not adapters else 'Working…' if busy else 'Bluetooth off' if not powered else 'Scanning for devices' if discovering else 'Ready')))
    return state, devices[:64], adapter_path


def bounded_objects(objects):
    adapters = [(p, v) for p, v in objects.items() if ADAPTER in v][:8]
    devices = [(p, v) for p, v in objects.items() if DEVICE in v]
    devices.sort(key=lambda row: (not row[1][DEVICE].get('Connected', False), not row[1][DEVICE].get('Paired', False), row[0]))
    return dict(adapters + devices[:64])


class BluetoothControls(QObject):
    changed = Signal()
    notice = Signal(str)
    received = Signal(object)

    def __init__(self, enabled=True, parent=None):
        super().__init__(parent)
        self._state, self._devices, self._pairing = dict(EMPTY), [], {}
        self.received.connect(self.apply)
        self.worker = BluetoothBus(self) if enabled else None

    state = Property('QVariantMap', lambda self: dict(self._state), notify=changed)
    devices = Property('QVariantList', lambda self: [dict(row) for row in self._devices], notify=changed)
    pairing = Property('QVariantMap', lambda self: dict(self._pairing), notify=changed)

    @Slot(object)
    def apply(self, payload):
        state = payload.get('state', self._state)
        devices = payload.get('devices', self._devices)
        pairing = payload.get('pairing', self._pairing)
        if (state, devices, pairing) != (self._state, self._devices, self._pairing):
            self._state, self._devices, self._pairing = dict(state), [dict(row) for row in devices[:64]], dict(pairing)
            self.changed.emit()

    def send(self, method, *args):
        worker = self.worker
        if worker:
            worker.schedule(lambda: getattr(worker, method)(*args))

    def device_action(self, method, path):
        if not any(row['path'] == path for row in self._devices):
            self.notice.emit('This Bluetooth device is no longer available')
            return
        self.send(method, path)

    @Slot(bool)
    def setPowered(self, powered): self.send('set_powered', bool(powered))
    @Slot()
    def startDiscovery(self): self.send('start_discovery')
    @Slot()
    def stopDiscovery(self): self.send('stop_discovery')
    @Slot(str)
    def connectDevice(self, path): self.device_action('device_action', path)  # default Connect
    @Slot(str)
    def disconnectDevice(self, path):
        if any(row['path'] == path for row in self._devices): self.send('device_action', path, 'Disconnect')
        else: self.notice.emit('This Bluetooth device is no longer available')
    @Slot(str)
    def pairDevice(self, path): self.device_action('pair_device', path)
    @Slot(str)
    def forgetDevice(self, path): self.device_action('forget_device', path)
    @Slot()
    def cancelPairing(self): self.send('cancel_pairing')
    @Slot(bool)
    def answerPairing(self, accepted): self.send('answer_pairing', bool(accepted))
    @Slot(str)
    def submitPinCode(self, value): self.send('submit_code', 'pin', value)
    @Slot(str)
    def submitPasskey(self, value): self.send('submit_code', 'passkey', value)

    @Slot()
    def close(self):
        if self.worker:
            self.worker.close()
            self.worker = None


class BluetoothBus:
    def __init__(self, owner):
        self.owner = owner
        self.context = self.loop = self.connection = None
        self.stopping = False
        self.objects = {}
        self.operations = set()
        self.status = ''
        self.bluez_owner = ''
        self.generation = 0
        self.agent_registered = False
        self.agent_requested = False
        self.agent_path = '/org/orbit/BluetoothAgent/p' + str(os.getpid()) + '_' + format(id(self), 'x')
        self.agent_registration = None
        self.pairing_path = ''
        self.explicit_paths = set()
        self.pending = None
        self.pending_mode = ''
        self.pending_data = {}
        self.pairing_timeout = None
        self.discovery_timeout = None
        self.want_discovery = False
        self.discovery_adapter = ''
        self.discovery_pending_adapter = ''
        self.thread = threading.Thread(target=self.run, name='orbit-bluetooth', daemon=True)
        self.thread.start()

    def schedule(self, function):
        if not self.context or self.stopping:
            return
        source = self.GLib.idle_source_new()
        def invoke(*_):
            try: function()
            except Exception as error: self.error(error)
            return False
        source.set_callback(invoke)
        source.attach(self.context)

    def timer(self, seconds, function):
        source = self.GLib.timeout_source_new_seconds(seconds)
        def invoke(*_):
            function()
            return False
        source.set_callback(invoke)
        source.attach(self.context)
        return source

    def clear_timer(self, attribute):
        source = getattr(self, attribute)
        if source: source.destroy()
        setattr(self, attribute, None)

    def publish(self):
        state, devices, _ = inventory(self.objects, bool(self.operations), self.status)
        self.owner.received.emit(dict(state=state, devices=devices))

    def error(self, error):
        self.status = plain(error)
        self.owner.notice.emit(self.status)
        self.publish()

    def call(self, path, interface, method, signature='()', args=(), done=None, failed=None, key=None, timeout=12000, service=BLUEZ):
        if self.stopping:
            return
        if key and key in self.operations:
            return
        generation = self.generation
        if key:
            self.operations.add(key)
            self.status = ''
            self.publish()
        def finish(connection, result, *_):
            if self.stopping or generation != self.generation:
                return
            if key: self.operations.discard(key)
            try:
                reply = connection.call_finish(result).unpack()
                if done: done(reply)
            except Exception as error:
                if failed: failed(error)
                else: self.error(error)
            self.publish()
        try:
            self.connection.call(service, path, interface, method, self.GLib.Variant(signature, args), None, self.Gio.DBusCallFlags.NONE, timeout, None, finish, None)
        except Exception as error:
            if key: self.operations.discard(key)
            if failed: failed(error)
            else: self.error(error)

    def run(self):
        try:
            if '/usr/lib/python3/dist-packages' not in sys.path:
                sys.path.append('/usr/lib/python3/dist-packages')
            from gi.repository import Gio, GLib
            if self.stopping:return
            self.Gio, self.GLib = Gio, GLib
            self.context = GLib.MainContext.new()
            self.context.push_thread_default()
            self.loop = GLib.MainLoop.new(self.context, False)
            # Own this connection: closing it releases even a discovery/agent
            # request whose reply has not yet arrived, without affecting other
            # shell services using Gio's shared system-bus connection.
            address = Gio.dbus_address_get_for_bus_sync(Gio.BusType.SYSTEM, None)
            flags = Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION
            self.connection = Gio.DBusConnection.new_for_address_sync(address, flags, None, None)
            self.subscriptions = [
                self.connection.signal_subscribe('org.freedesktop.DBus', 'org.freedesktop.DBus', 'NameOwnerChanged', '/org/freedesktop/DBus', BLUEZ, Gio.DBusSignalFlags.NONE, self.owner_changed),
                self.connection.signal_subscribe(BLUEZ, OBJECTS, None, '/', None, Gio.DBusSignalFlags.NONE, self.object_changed),
                self.connection.signal_subscribe(BLUEZ, PROPERTIES, 'PropertiesChanged', None, None, Gio.DBusSignalFlags.NONE, self.properties_changed),
            ]
            info = Gio.DBusNodeInfo.new_for_xml(AGENT_XML)
            self.agent_registration = self.connection.register_object(self.agent_path, info.interfaces[0], self.agent_method, None, None)
            self.call('/org/freedesktop/DBus', 'org.freedesktop.DBus', 'GetNameOwner', '(s)', (BLUEZ,), done=lambda reply:self.attach(reply[0]), failed=lambda _:self.publish(), service='org.freedesktop.DBus')
            if self.stopping:
                self.connection.unregister_object(self.agent_registration)
                for subscription in self.subscriptions:self.connection.signal_unsubscribe(subscription)
                self.connection.close_sync(None)
            else:self.loop.run()
            self.context.pop_thread_default()
        except Exception as error:
            if not self.stopping: self.error('Bluetooth unavailable: ' + plain(error))

    def attach(self, owner):
        self.bluez_owner = owner
        generation = self.generation
        def loaded(reply):
            if generation != self.generation:return
            self.objects = bounded_objects(reply[0])
            self.publish()
        self.call('/', OBJECTS, 'GetManagedObjects', done=loaded)
        self.agent_requested = True
        self.call('/org/bluez', MANAGER, 'RegisterAgent', '(os)', (self.agent_path, 'KeyboardDisplay'), done=lambda _:setattr(self, 'agent_registered', True))

    def owner_changed(self, *args):
        name, old, new = args[-1].unpack()
        self.generation += 1
        self.cancel_pending('Bluetooth service changed')
        self.clear_timer('discovery_timeout')
        self.objects.clear()
        self.operations.clear()
        self.explicit_paths.clear()
        self.pairing_path = self.discovery_adapter = self.discovery_pending_adapter = ''
        self.want_discovery = self.agent_registered = self.agent_requested = False
        self.status = ''
        self.bluez_owner = new
        self.publish()
        if new: self.attach(new)

    def object_changed(self, *args):
        member, values = args[-2], args[-1].unpack()
        if member == 'InterfacesAdded':
            path, interfaces = values
            self.objects[path] = {**self.objects.get(path, {}), **interfaces}
            self.objects = bounded_objects(self.objects)
        elif member == 'InterfacesRemoved':
            path, interfaces = values
            entry = self.objects.get(path, {})
            for interface in interfaces: entry.pop(interface, None)
            if not entry:self.objects.pop(path, None)
            if DEVICE in interfaces and (path == self.pairing_path or path==getattr(self,'pending_data',{}).get('path')):self.cancel_pairing()
        self.publish()

    def properties_changed(self, *args):
        path, values = args[2], args[-1].unpack()
        interface, changed, invalidated = values
        if interface not in (ADAPTER, DEVICE, BATTERY) or path not in self.objects:return
        properties = self.objects[path].setdefault(interface, {})
        properties.update(changed)
        for name in invalidated: properties.pop(name, None)
        if invalidated:
            def refreshed(reply):
                if path in self.objects and interface in self.objects[path]:self.objects[path][interface] = reply[0]
            def failed(error):
                if path in self.objects and interface in self.objects[path]:self.error(error)
            self.call(path, PROPERTIES, 'GetAll', '(s)', (interface,), done=refreshed, failed=failed)
        if interface == ADAPTER and changed.get('Powered') is False:
            self.stop_discovery()
        self.status = ''
        self.publish()

    def adapter(self): return inventory(self.objects)[2]
    def known(self, path): return path in self.objects and DEVICE in self.objects[path]

    def set_powered(self, value):
        path = self.adapter()
        if not path:return self.error('No Bluetooth adapter available')
        if not value:
            self.stop_discovery();self.cancel_pairing()
            targets=[name for name, interfaces in self.objects.items()
                     if interfaces.get(ADAPTER, {}).get('Powered') is True]
        else:
            targets=[path]
        for target in targets:
            self.call(target, PROPERTIES, 'Set', '(ssv)',
                      (ADAPTER, 'Powered', self.GLib.Variant('b', bool(value))), key='power:'+target)

    def start_discovery(self):
        path = self.adapter()
        if not path:return self.error('No Bluetooth adapter available')
        if self.objects[path][ADAPTER].get('Powered') is not True:return self.error('Turn Bluetooth on before scanning')
        if self.discovery_adapter or 'scan-start' in self.operations:return
        self.want_discovery = True
        self.discovery_pending_adapter = path
        def started(_):
            self.discovery_pending_adapter = ''
            self.discovery_adapter = path
            if not self.want_discovery:return self.stop_discovery()
            self.clear_timer('discovery_timeout')
            self.discovery_timeout = self.timer(30, self.stop_discovery)
        def failed(error):
            self.discovery_pending_adapter = ''
            self.want_discovery = False
            self.error(error)
        self.call(path, ADAPTER, 'StartDiscovery', done=started, failed=failed, key='scan-start')

    def stop_discovery(self):
        self.want_discovery = False
        self.clear_timer('discovery_timeout')
        path = self.discovery_adapter
        if not path:return
        def stopped(_): self.discovery_adapter = ''
        self.call(path, ADAPTER, 'StopDiscovery', done=stopped, key='scan-stop', timeout=5000)

    def device_action(self, path, method='Connect'):
        if method not in ('Connect', 'Disconnect') or not self.known(path):return self.error('This Bluetooth device is no longer available')
        self.explicit_paths.add(path)
        def ended(_):self.explicit_paths.discard(path)
        def failed(error):self.explicit_paths.discard(path);self.error(error)
        self.call(path, DEVICE, method, done=ended, failed=failed, key=method + ':' + path, timeout=30000)

    def forget_device(self, path):
        if not self.known(path):return self.error('This Bluetooth device is no longer available')
        adapter = self.objects[path][DEVICE].get('Adapter') or self.adapter()
        if adapter not in self.objects or ADAPTER not in self.objects[adapter]:return self.error('Bluetooth adapter is no longer available')
        if not self.objects[path][DEVICE].get('Paired'):return self.error('This device is not paired')
        self.call(adapter, ADAPTER, 'RemoveDevice', '(o)', (path,), key='forget:' + path)

    def pair_device(self, path):
        if not self.known(path):return self.error('This Bluetooth device is no longer available')
        if not self.agent_registered:return self.error('Bluetooth pairing agent is not ready')
        if self.pairing_path:return self.error('Finish the current pairing first')
        self.pairing_path = path
        self.explicit_paths.add(path)
        def ended(_):self.finish_pair(path)
        def failed(error):
            # A client-side D-Bus timeout does not cancel BlueZ's remote work.
            if self.known(path):self.call(path, DEVICE, 'CancelPairing', failed=lambda _:None, timeout=2000)
            self.finish_pair(path)
            self.error(error)
        self.call(path, DEVICE, 'Pair', done=ended, failed=failed, key='pair:' + path, timeout=60000)

    def finish_pair(self, path):
        self.cancel_pending('Pairing finished')
        if self.pairing_path == path:self.pairing_path = ''
        self.explicit_paths.discard(path)
        self.owner.received.emit({'pairing': {}})

    def cancel_pairing(self):
        self.cancel_pending('Pairing canceled')
        self.owner.received.emit({'pairing': {}})
        path = self.pairing_path
        if path and self.known(path):self.call(path, DEVICE, 'CancelPairing', key='cancel:' + path, timeout=5000)

    def cancel_pending(self, reason='Pairing canceled'):
        self.clear_timer('pairing_timeout')
        if self.pending:
            pending, self.pending = self.pending, None
            pending.return_dbus_error(BLUEZ + '.Error.Canceled', reason)
        self.pending_mode = '';self.pending_data = {}
        self.owner.received.emit({'pairing': {}})

    def answer_pairing(self, accepted):
        if accepted and getattr(self,'pending_mode','') in ('pin','passkey'):
            return self.owner.notice.emit('Enter the requested pairing code before continuing')
        self.clear_timer('pairing_timeout')
        if not self.pending:return
        pending, self.pending = self.pending, None
        if accepted:pending.return_value(self.GLib.Variant('()', ()))
        else:pending.return_dbus_error(BLUEZ + '.Error.Rejected', 'Pairing rejected by user')
        self.pending_mode = '';self.pending_data = {}
        self.owner.received.emit({'pairing': {}})

    def submit_code(self, mode, value):
        """Answer only the current explicit request; never retain or log the code."""
        if not self.pending or mode!=getattr(self,'pending_mode',''):return
        data=getattr(self,'pending_data',{})
        path=data.get('path')
        if not self.bluez_owner or not self.known(path) or path not in self.explicit_paths:
            return self.cancel_pending('Pairing device is no longer available')
        valid=isinstance(value,str) and (1<=len(value)<=16 and value.strip() and all(32<=ord(c)<=126 for c in value) if mode=='pin' else 1<=len(value)<=6 and value.isascii() and value.isdigit())
        if not valid:
            message='PIN must contain 1–16 printable characters.' if mode=='pin' else 'Passkey must contain one to six digits.'
            self.owner.received.emit({'pairing':dict(data,error=message)})
            return
        pending,self.pending=self.pending,None
        self.pending_mode='';self.pending_data={};self.clear_timer('pairing_timeout')
        pending.return_value(self.GLib.Variant('(s)' if mode=='pin' else '(u)',(value if mode=='pin' else int(value),)))
        self.owner.received.emit({'pairing':{}})

    def agent_method(self, connection, sender, path, interface, method, parameters, invocation):
        def reject(message):invocation.return_dbus_error(BLUEZ + '.Error.Rejected', message)
        if sender != self.bluez_owner or not self.bluez_owner:return reject('Unknown pairing service')
        if method == 'Release':
            self.agent_registered = False
            self.cancel_pending('Pairing agent released')
            invocation.return_value(self.GLib.Variant('()', ()))
            return
        if method == 'Cancel':
            self.cancel_pending()
            invocation.return_value(self.GLib.Variant('()', ()))
            return
        args = parameters.unpack()
        device_path = args[0] if args else ''
        if not self.known(device_path) or device_path not in self.explicit_paths:return reject('Pairing was not initiated in Orbit')
        name = plain(self.objects[device_path][DEVICE].get('Alias') or self.objects[device_path][DEVICE].get('Name') or 'Bluetooth device')
        data = dict(path=device_path, name=name, mode='display', passkey='', entered=0, service='')
        if method in ('RequestPinCode', 'RequestPasskey'):
            if self.pending:return reject('Another pairing request is pending')
            data['mode']='pin' if method=='RequestPinCode' else 'passkey'
            self.pending=invocation;self.pending_mode=data['mode'];self.pending_data=dict(data)
            self.owner.received.emit({'pairing':data})
            self.pairing_timeout=self.timer(30,self.cancel_pairing)
            return
        if method in ('RequestConfirmation', 'DisplayPasskey'):
            if not 0 <= args[1] <= 999999:return reject('Invalid passkey')
            data['passkey'] = f'{args[1]:06d}'
            if method == 'DisplayPasskey':data['entered'] = max(0, min(6, args[2]))
        elif method == 'DisplayPinCode':data['passkey'] = plain(args[1], 16)
        elif method == 'AuthorizeService':data['service'] = plain(args[1], 100)
        elif method != 'RequestAuthorization':return reject('Unsupported pairing request')
        if method in ('DisplayPinCode', 'DisplayPasskey'):
            self.owner.received.emit({'pairing': data})
            invocation.return_value(self.GLib.Variant('()', ()))
            return
        if self.pending:return reject('Another pairing confirmation is pending')
        data['mode'] = 'confirm' if method == 'RequestConfirmation' else 'authorize'
        self.pending = invocation
        self.pending_mode = data['mode'];self.pending_data = dict(data)
        self.owner.received.emit({'pairing': data})
        self.pairing_timeout = self.timer(30, self.cancel_pairing)

    def shutdown(self):
        if self.stopping:return
        try:
            self.cancel_pending('Mellipi is closing')
            self.clear_timer('discovery_timeout')
            # Release only requests made by our dedicated connection. Requests
            # are ordered, so StopDiscovery also covers a pending Start reply.
            for path, interface, method, signature, args in [
                (self.discovery_adapter or self.discovery_pending_adapter, ADAPTER, 'StopDiscovery', '()', ()),
                (self.pairing_path, DEVICE, 'CancelPairing', '()', ()),
                ('/org/bluez' if self.agent_registered or self.agent_requested else '', MANAGER, 'UnregisterAgent', '(o)', (self.agent_path,)),
            ]:
                if path:
                    self.connection.call(BLUEZ, path, interface, method, self.GLib.Variant(signature, args), None, self.Gio.DBusCallFlags.NONE, 1000, None, None, None)
            self.connection.flush_sync(None)
        finally:
            if self.agent_registration:self.connection.unregister_object(self.agent_registration)
            for subscription in getattr(self, 'subscriptions', []):self.connection.signal_unsubscribe(subscription)
            try:self.connection.close_sync(None)
            except Exception:pass
            self.stopping = True
            self.loop.quit()

    def close(self):
        if self.context and self.loop and not self.stopping:self.schedule(self.shutdown)
        else:self.stopping = True
        self.thread.join(timeout=3)
