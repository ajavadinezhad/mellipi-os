"""Small static search destinations; no index, history or background service."""
SETTING_ACTIONS=(
    dict(id='microphone',name='Microphone',description='Choose microphone input and recording level',icon='audio-input-microphone',words='mic microphone input wired headset usb recording mute unmute volume level',section=8,tab=0,target='inputDevicePickerToggle'),
    dict(id='density',name='Interface density',description='Comfortable, compact or extra compact controls',icon='view-grid',words='density compact extra compact comfortable spacing smaller interface',section=10,tab=0,target='densitySegments'),
    dict(id='pointer',name='Mouse pointer',description='Use the theme accent for Mellipi’s arrow pointer',icon='input-mouse',words='pointer cursor mouse arrow theme accent',section=10,tab=0,target='cursorAccentToggle'),
    dict(id='brightness',name='Display brightness',description='Adjust display brightness and external monitor controls',icon='display-brightness',words='brightness dim hdmi ddc monitor screen light',section=15,tab=0,target='brightnessSlider'),
    dict(id='battery-health',name='Battery health',description='Battery condition and supported charging limits',icon='battery',words='battery health charge charging limit 80 60 percent lifespan',section=7,tab=0,target='chargeLimitOptions'),
    dict(id='wallpaper',name='Desktop wallpaper',description='Choose the desktop background',icon='preferences-desktop-wallpaper',words='wallpaper background solid dusk picture',section=10,tab=1,target='wallpaperStyleSegments'),
    dict(id='desktop-animations',name='Desktop animations',description='Reduce motion or change animation settings',icon='preferences-desktop-effects',words='animations effects motion speed transitions reduce accessibility',section=10,tab=2,target='motionReduceToggle'),
    dict(id='text-size',name='Desktop text size',description='Change the size of text in Mellipi',icon='preferences-desktop-accessibility',words='font text size scale readability accessibility larger smaller',section=10,tab=0,target='appearanceTextScaleToggle'),
    dict(id='high-contrast',name='High contrast',description='Toggle higher contrast for the active theme',icon='color-select',words='high contrast visibility reading accessibility',section=10,tab=0,target='highContrastToggle'),
    dict(id='arrange-quick-controls',name='Arrange Quick Settings',description='Reorder the controls on the main Quick Settings view',icon='view-grid',words='arrange controls quick settings layout move reorder',section=-1,tab=0,target=''),
    dict(id='default-apps',name='Default applications',description='Choose browser, file manager and file-type defaults',icon='application-x-executable',words='default apps browser open with file types associations',section=16,tab=0,target='defaultTypePicker'),
    dict(id='startup-apps',name='Startup applications',description='Add apps or change what starts at the next login',icon='system-run',words='startup autostart launch login background boot',section=16,tab=1,target='startupApplications'),
    dict(id='removable-devices',name='Removable devices',description='Open, mount or safely eject a drive',icon='drive-removable-media',words='usb disk drive removable mount unmount eject encrypted storage',section=16,tab=2,target='removableDevices'),
    dict(id='install-apps',name='Install applications',description='Open the installed software manager',icon='system-software-install',words='software install applications packages apt flatpak flathub snap store',section=16,tab=3,target='systemTool_software'),
    dict(id='software-updates',name='Software updates',description='Open the installed update manager',icon='software-update-available',words='updates upgrade software packages',section=16,tab=3,target='systemTool_updates'),
    dict(id='user-accounts',name='Users and passwords',description='Open user account settings',icon='system-users',words='users accounts password login avatar profile',section=16,tab=3,target='systemTool_users'),
    dict(id='date-time',name='Date and time',description='Open time, timezone and clock settings',icon='preferences-system-time',words='date time timezone clock ntp automatic',section=16,tab=3,target='systemTool_datetime'),
    dict(id='backups',name='Backups and recovery',description='Back up files, restore settings or find your working desktop version',icon='document-revert',words='backup back up restore recovery undo update downgrade working version safe rescue repair files',section=16,tab=3,target='systemTool_recovery'),
)
SETTING_TARGETS={row['id']:(row['section'],row['tab'],row['target']) for row in SETTING_ACTIONS if row['target']}
SETTING_TARGETS['reduced-motion']=SETTING_TARGETS['desktop-animations']
BUILTIN_TOOLS={'user-accounts':'users','date-time':'datetime','backups':'recovery'}

def setting_actions():
    return [dict(id=r['id'],name=r['name'],description=r['description'],icon=r['icon'],searchText=' '.join((r['name'],r['description'],r['words'])).lower(),destination='setting:'+r['id'],section=r['section']) for r in SETTING_ACTIONS]
