#!/usr/bin/env python3
"""Build a private, pinned Qt5 Wayland accessibility compatibility library.

No apt installation, root execution or system library replacement. Build with
one low-priority compiler. Only this desktop's Qt5 processes may use the result.
"""
import argparse,hashlib,json,os,shutil,subprocess,tarfile,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def run(command,cwd=None,env=None):subprocess.run(command,cwd=cwd,env=env,check=True)
def download(row,target):
    if target.is_file() and digest(target)==row['sha256']:return
    with urllib.request.urlopen(row['url'],timeout=60) as incoming,target.open('wb') as output:shutil.copyfileobj(incoming,output)
    if digest(target)!=row['sha256']:target.unlink();raise ValueError('SHA256 mismatch: '+row['name'])
def build(work,inputs,output,jobs=1):
    expected={'libqt5waylandclient5':'5.15.13-1','libqt5core5t64':'5.15.13+dfsg-1ubuntu1','libqt5gui5t64':'5.15.13+dfsg-1ubuntu1'}
    for package,version in expected.items():
        actual=subprocess.check_output(['dpkg-query','-W','-f=${Version}',package],text=True)
        if actual!=version:raise ValueError('This pinned compatibility build requires '+package+'='+version)
    work=work.resolve();work.mkdir(parents=True,exist_ok=True);downloads=work/'downloads';downloads.mkdir(exist_ok=True)
    sysroot=work/'sysroot';sysroot.mkdir(exist_ok=True)
    for row in inputs['downloads']:
        target=downloads/row['name'];download(row,target)
        if row['kind']=='deb':run(['dpkg-deb','-x',str(target),str(sysroot)])
    prefix=sysroot/'usr';lib=prefix/'lib/x86_64-linux-gnu'
    for path in lib.glob('*.so'):
        if path.is_symlink() and not path.exists():
            host=Path('/usr/lib/x86_64-linux-gnu')/path.readlink().name
            if host.exists():path.unlink();path.symlink_to(host.resolve())
    qbin=prefix/'lib/qt5/bin';qmake=qbin/'qmake'
    (qbin/'qt.conf').write_text('[Paths]\nPrefix='+str(prefix)+'\nHeaders=include/x86_64-linux-gnu/qt5\nLibraries=lib/x86_64-linux-gnu\nArchData=lib/x86_64-linux-gnu/qt5\nData=share/qt5\nHostData=lib/x86_64-linux-gnu/qt5\nHostBinaries=lib/qt5/bin\n')
    source=work/'qtwayland-everywhere-src-5.15.13'
    if not source.is_dir():
        with tarfile.open(downloads/'qtwayland.tar.xz') as archive:archive.extractall(work,filter='data')
    wayland_debian=work/'wayland-debian';qtbase_debian=work/'qtbase-debian'
    for name,destination in [('qtwayland-opensource-src_5.15.13-1.debian.tar.xz',wayland_debian),('qtbase-opensource-src_5.15.13+dfsg-1ubuntu1.debian.tar.xz',qtbase_debian)]:
        destination.mkdir(exist_ok=True)
        with tarfile.open(downloads/name) as archive:archive.extractall(destination,filter='data')
    patch_marker=source/'.abstract-distro-patches-applied'
    if not patch_marker.exists():
        series=wayland_debian/'debian/patches/series'
        for line in series.read_text().splitlines():
            name=line.strip()
            if name and not name.startswith('#'):
                run(['patch','-p1','--forward','--batch','-i',str(series.parent/name)],source)
        patch_marker.write_text('All installed-distribution patches applied.\n')
    bridge=work/'bridge';bridge.mkdir(exist_ok=True)
    qtbase_source=work/'qtbase-source';qtbase_bridge=qtbase_source/'src/platformsupport/linuxaccessibility';qtbase_bridge.mkdir(parents=True,exist_ok=True)
    shutil.copy2(downloads/'bridge.cpp',qtbase_bridge/'bridge.cpp')
    run(['patch','-p1','--batch','-i',str(qtbase_debian/'debian/patches/a11y_root.diff')],qtbase_source)
    patch_source=(qtbase_bridge/'bridge.cpp').read_text();needle='if (!dbusAdaptor && isActive()) {'
    if patch_source.count(needle)!=1:raise ValueError('Unexpected Qt bridge source')
    (bridge/'bridge.cpp').write_text(patch_source.replace(needle,'if (!dbusAdaptor && isActive() && dbusConnection->connection().isConnected()) {'))
    shutil.copy2(downloads/'DeviceEventController.xml',bridge/'DeviceEventController.xml')
    shutil.copy2(downloads/'Bus.xml',bridge/'Bus.xml')
    connection=(downloads/'dbusconnection.cpp').read_text().replace('    connect(dbusWatcher, SIGNAL(serviceRegistered(QString)), this, SLOT(serviceRegistered()));','    connect(dbusWatcher, SIGNAL(serviceRegistered(QString)), this, SLOT(serviceRegistered()));\n    c.connect(A11Y_SERVICE, A11Y_PATH, QLatin1String("org.freedesktop.DBus.Properties"),\n              QLatin1String("PropertiesChanged"), this, SLOT(serviceRegistered()));').replace('    bool enabled = a11yAlwaysOn || a11yStatus->screenReaderEnabled() || a11yStatus->isEnabled();','    bool enabled = a11yAlwaysOn || a11yStatus->screenReaderEnabled() || a11yStatus->isEnabled();\n    a11yStatus->deleteLater();')
    (bridge/'dbusconnection.cpp').write_text(connection)
    run([str(qbin/'qdbusxml2cpp'),'-i','struct_marshallers_p.h','-a','deviceeventcontroller_adaptor','DeviceEventController.xml'],bridge)
    run([str(qbin/'qdbusxml2cpp'),'-i','struct_marshallers_p.h','-p','bus_interface','Bus.xml'],bridge)
    include=prefix/'include/x86_64-linux-gnu/qt5';includes=[include,prefix/'include/at-spi-2.0']
    for module in ('QtCore','QtGui','QtDBus','QtLinuxAccessibilitySupport'):includes.extend([include/module,include/module/'5.15.13',include/module/'5.15.13'/module])
    includes.append(include/'QtLinuxAccessibilitySupport/5.15.13/QtLinuxAccessibilitySupport/private')
    run(['nice','-n','15','g++','-std=c++17','-fPIC','-fvisibility=hidden','-O2','-DQT_NO_CAST_FROM_ASCII',*('-I'+str(p) for p in includes),'-c','bridge.cpp','-o','bridge.o'],bridge)
    run(['nice','-n','15','g++','-std=c++17','-fPIC','-fvisibility=hidden','-O2','-DQT_NO_CAST_FROM_ASCII',*('-I'+str(p) for p in includes),'-c','dbusconnection.cpp','-o','dbusconnection.o'],bridge)
    run(['ar','r',str(lib/'libQt5LinuxAccessibilitySupport.a'),'bridge.o','dbusconnection.o'],bridge)
    builddir=work/'wayland-build';builddir.mkdir(exist_ok=True);(builddir/'config.cache').unlink(missing_ok=True)
    env=dict(os.environ,PATH=str(prefix/'bin')+':'+os.environ.get('PATH',''),PKG_CONFIG_PATH=str(lib/'pkgconfig'),PKG_CONFIG_SYSROOT_DIR=str(sysroot))
    run([str(qmake),str(source/'qtwayland.pro'),'--','-no-feature-wayland-server'],builddir,env)
    # Keep private feature definitions identical to the distribution plugins.
    shutil.copy2(include/'QtWaylandClient/5.15.13/QtWaylandClient/private/qtwaylandclient-config_p.h',builddir/'src/client/qtwaylandclient-config_p.h')
    run([str(qmake),str(source/'src/src.pro')],builddir/'src',env)
    # Preserve O2 and distro hardening, omit debug data from this small runtime.
    client=builddir/'src/client'
    run([str(qmake),str(source/'src/client/client.pro')],client,env)
    flags=next(line.split('=',1)[1].strip() for line in (client/'Makefile').read_text().splitlines() if line.startswith('CXXFLAGS '))
    flags=' '.join(flag for flag in flags.split() if flag!='-g')
    run(['nice','-n','15','make','-j'+str(jobs),'sub-client','CXXFLAGS='+flags],builddir/'src',env)
    output.mkdir(parents=True,exist_ok=True);(output/'lib').mkdir(exist_ok=True)
    binary=output/'lib/libQt5WaylandClient.so.5';shutil.copy2(builddir/'lib/libQt5WaylandClient.so.5.15.13',binary);run(['strip','--strip-unneeded',str(binary)])
    for name in ('LICENSE.LGPL3','LICENSE.GPL2','LICENSE.GPL3'):shutil.copy2(source/name,output/name)
    for name,folder in [('qtwayland',wayland_debian),('qtbase',qtbase_debian)]:shutil.copy2(folder/'debian/copyright',output/(name+'-copyright'))
    dynamic=subprocess.check_output(['readelf','-d',str(binary)],text=True)
    if '(RUNPATH)' in dynamic or '(RPATH)' in dynamic or any('/' in line.split('[',1)[1].split(']',1)[0] for line in dynamic.splitlines() if '(NEEDED)' in line):raise ValueError('Candidate has nonportable dynamic dependencies')
    shutil.copy2(ROOT/'patches/qt5-a11y-connection-ready.patch',output/'qt5-a11y-connection-ready.patch')
    manifest=dict(qt_version=inputs['qt_version'],inputs=inputs['downloads'],binary_sha256=digest(binary),system_libraries={str(p):digest(p) for p in (Path('/usr/lib/x86_64-linux-gnu/libQt5WaylandClient.so.5'),Path('/usr/lib/x86_64-linux-gnu/libQt5Core.so.5'),Path('/usr/lib/x86_64-linux-gnu/libQt5Gui.so.5'))})
    manifest.update(distribution_patch_series=[line.strip() for line in (wayland_debian/'debian/patches/series').read_text().splitlines() if line.strip() and not line.lstrip().startswith('#')],qtbase_bridge_distribution_patches=['a11y_root.diff'],custom_patch_sha256=digest(ROOT/'patches/qt5-a11y-connection-ready.patch'))
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--workdir',type=Path,default=ROOT/'.qt5-a11y-build');parser.add_argument('--output',type=Path,default=ROOT/'.qt5-a11y-runtime');parser.add_argument('--jobs',type=int,choices=(1,2),default=1);args=parser.parse_args()
    if os.geteuid()==0:parser.error('Run as your desktop user, without sudo')
    inputs=json.loads((ROOT/'tools/qt5-a11y-inputs.json').read_text());build(args.workdir,inputs,args.output,args.jobs)
if __name__=='__main__':main()
