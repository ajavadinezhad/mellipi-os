#!/usr/bin/env python3
"""Build only Noble's Calamares partition plugin in a private userspace SDK.

No package installation, disks, mounts, installed desktop or system libraries are
modified. Inputs must be extracted Ubuntu Noble packages and pristine 3.3.5
source. Preserve Ubuntu's encryption-layout patch before our two narrow fixes.
"""
import argparse,hashlib,json,os,shutil,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ORIGINAL_ACTIONS='cb5fe54a37b2e4b8b333219cbbd2b52b8d8c964d01137568d57cf71e2bce1b60'
UBUNTU_PATCH='a491cc61c4616eb7611cc7491fccf48451f1ee3c5042339b538014a3e4154b8b'
def sha(path):
 with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def run(args,**kwargs):return subprocess.run([str(x) for x in args],check=True,**kwargs)
def main():
 p=argparse.ArgumentParser(description=__doc__)
 for name in ['source-dir','ubuntu-encryption-patch','calamares-prefix','development-prefix','qt-prefix','build-dir','output']:p.add_argument('--'+name,type=Path,required=True)
 a=p.parse_args()
 for key,value in vars(a).items():
  value=value.resolve();setattr(a,key,value)
  if any(c.isspace() for c in str(value)):p.error('SDK/build paths must not contain whitespace')
 source=a.source_dir/'src/modules/partition';assert sha(source/'core/PartitionActions.cpp')==ORIGINAL_ACTIONS,'Use pristine upstream 3.3.5 source'
 assert sha(a.ubuntu_encryption_patch)==UBUNTU_PATCH,'Use the exact Noble 3.3.5-0ubuntu4 encryption patch'
 assert not a.build_dir.exists() and not a.output.exists(),'Use new private build/output paths'
 a.build_dir.mkdir(parents=True);src=a.build_dir/'source/src/modules/partition';shutil.copytree(source,src)
 patches=[a.ubuntu_encryption_patch,ROOT/'desktop/patches/calamares-gpt-usable-boundary.patch',ROOT/'desktop/patches/calamares-default-encryption-flag.patch']
 for patch in patches:
  with patch.open('rb') as f:run(['patch','--batch','--forward','-d',a.build_dir/'source','-p1'],stdin=f)
 inc=a.development_prefix/'include';lib=a.development_prefix/'lib/x86_64-linux-gnu';cal=a.calamares_prefix;qt=a.qt_prefix
 sdk=[lib,cal/'lib/x86_64-linux-gnu',qt/'lib/x86_64-linux-gnu'];env=dict(os.environ,LIBRARY_PATH=':'.join(map(str,sdk)),LD_LIBRARY_PATH=':'.join(map(str,sdk)))
 includes=[src,cal/'include/libcalamares',inc,inc/'kpmcore',inc/'KF5',*[inc/'KF5'/n for n in ['KCoreAddons','KI18n','KWidgetsAddons','KConfigCore','KConfigGui']]]
 lines=['TEMPLATE = lib','CONFIG += plugin c++17','CONFIG -= debug','TARGET = calamares_viewmodule_partition','QT += core gui widgets concurrent dbus','DEFINES += PLUGINDLLEXPORT_PRO','INCLUDEPATH += '+' '.join(map(str,includes)),'LIBS += -L'+str(sdk[1])+' -lcalamaresui -lcalamares -L'+str(lib)+' -lkpmcore','QMAKE_LFLAGS += -Wl,-z,defs '+' '.join('-Wl,-rpath-link,'+str(d) for d in sdk)]
 for key,glob in [('SOURCES','*.cpp'),('HEADERS','*.h'),('FORMS','*.ui')]:lines.append(key+' += '+' '.join(str(f) for f in sorted(src.rglob(glob)) if 'tests' not in f.relative_to(src).parts))
 build=a.build_dir/'build';build.mkdir();(build/'partition.pro').write_text('\n'.join(lines)+'\n')
 run([qt/'lib/qt5/bin/qmake','partition.pro'],cwd=build,env=env);run(['nice','-n','15','make','-j1'],cwd=build,env=env)
 module=build/'libcalamares_viewmodule_partition.so';assert module.read_bytes()[:4]==b'\x7fELF'
 # Exercise the actual KPMCore usable-end API and the plugin's constructor,
 # using a nonexistent fake device path (never a real block device).
 test=build/'geometry-test';test.mkdir();shutil.copy2(ROOT/'tests/fixtures/calamares_partition_geometry.cpp',test/'geometry.cpp')
 test_lines=['TEMPLATE = app','CONFIG += console c++17','QT += core gui widgets','TARGET = geometry','SOURCES = geometry.cpp','INCLUDEPATH += '+' '.join(map(str,includes)),'LIBS += -L'+str(build)+' -L'+str(sdk[1])+' -lcalamaresui -lcalamares -L'+str(lib)+' -lkpmcore','QMAKE_LFLAGS += '+' '.join('-Wl,-rpath-link,'+str(d) for d in [build,*sdk])]
 (test/'geometry.pro').write_text('\n'.join(test_lines)+'\n');run([qt/'lib/qt5/bin/qmake','geometry.pro'],cwd=test,env=env);run(['nice','-n','15','make','-j1'],cwd=test,env=env)
 check_env=dict(env,QT_QPA_PLATFORM='offscreen',LD_LIBRARY_PATH=str(build)+':'+env['LD_LIBRARY_PATH']);geometry=json.loads(subprocess.check_output([str(test/'geometry'),str(module)],env=check_env,text=True))
 run(['strip','--strip-unneeded',module]);a.output.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(module,a.output)
 report={'upstream':'Calamares 3.3.5','ubuntu_package':'3.3.5-0ubuntu4','module_sha256':sha(a.output),'module_bytes':a.output.stat().st_size,'source_actions_sha256':ORIGINAL_ACTIONS,'patches':{('enable-only-present-with-encryption-partitions.patch' if n==0 else f.name):sha(f) for n,f in enumerate(patches)},'sdk_versions':{'qt':'5.15.13','kpmcore':'23.08.5'},'geometry_regression':geometry,'jobs':1,'host_packages_installed':False,'module_only':True}
 a.output.with_suffix(a.output.suffix+'.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
if __name__=='__main__':main()
