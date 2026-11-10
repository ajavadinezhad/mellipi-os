#!/usr/bin/env python3
"""Replace a GRUB rescue ISO's unsigned EFI image with Ubuntu's signed chain.

Called by the guarded disposable-guest builder. Does not enroll keys, mount
filesystems, access disks, or change workstation firmware. Trust acceptance
still requires an actual Secure Boot VM/hardware boot, not sbverify --list.
"""
import argparse,hashlib,json,shutil,subprocess
from pathlib import Path

def run(args,**kw):return subprocess.run(list(map(str,args)),check=True,**kw)
def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def build(source,output,root,work):
    source,output,root,work=map(Path,(source,output,root,work))
    if not source.is_file() or source.is_symlink() or output.exists() or output.is_symlink():raise ValueError('Use a regular source ISO and a new output filename')
    if not work.is_dir() or any(work.iterdir()):raise ValueError('Use a new empty dedicated boot-image work directory')
    candidates={'bootx64.efi':root/'usr/lib/shim/shimx64.efi.signed.latest','grubx64.efi':root/'usr/lib/grub/x86_64-efi-signed/gcdx64.efi.signed','mmx64.efi':root/'usr/lib/shim/mmx64.efi'}
    if not candidates['bootx64.efi'].is_file():candidates['bootx64.efi']=root/'usr/lib/shim/shimx64.efi.signed'
    rows={}
    for name,path in candidates.items():
        if not path.is_file():raise ValueError('Missing signed Ubuntu boot component: '+str(path))
        # This is a structural signature gate, not firmware trust certification.
        check=run(['sbverify','--list',path],capture_output=True,text=True)
        if 'signature 1' not in check.stdout:raise ValueError('Unsigned EFI component: '+name)
        rows[name]={'sha256':sha(path),'bytes':path.stat().st_size,'signature_present':True}
    kernel=work/'kernel'
    run(['xorriso','-osirrox','on','-indev',source,'-extract','/casper/vmlinuz',kernel],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    check=run(['sbverify','--list',kernel],capture_output=True,text=True)
    if 'signature 1' not in check.stdout:raise ValueError('Live kernel lacks a PE signature')
    kernel.unlink()
    efi=work/'efi';boot=efi/'EFI/BOOT';ubuntu=efi/'EFI/ubuntu';boot.mkdir(parents=True);ubuntu.mkdir(parents=True)
    for name,path in candidates.items():shutil.copyfile(path,boot/name)
    config="search --file --set=root /.disk/casper-uuid-generic\nset prefix=($root)/boot/grub\nconfigfile $prefix/grub.cfg\n"
    for p in (boot/'grub.cfg',ubuntu/'grub.cfg'):p.write_text(config)
    fat=work/'signed-efi.img'
    with fat.open('xb') as f:f.truncate(16*1024*1024)
    run(['mkfs.vfat','-n','MELLIPI_EFI',fat],stdout=subprocess.DEVNULL)
    run(['mcopy','-s','-i',fat,efi/'EFI','::/'])
    tree=work/'iso';tree.mkdir()
    run(['xorriso','-osirrox','on','-indev',source,'-extract','/',tree],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    (tree/'efi.img').unlink(missing_ok=True)
    shutil.copytree(efi/'EFI',tree/'EFI',dirs_exist_ok=True)
    mbr=Path('/usr/lib/grub/i386-pc/boot_hybrid.img')
    if not mbr.is_file() or not (tree/'boot/grub/i386-pc/eltorito.img').is_file():raise ValueError('Missing BIOS hybrid boot inputs')
    # Give the signed EFI FAT its own appended GPT partition. Replaying the
    # old 2.8MB EFI partition table with this larger image can overlap GPT.
    run(['xorriso','-as','mkisofs','-r','-V','MELLIPI_LIVE','-o',output,
         '--grub2-mbr',mbr,'-partition_offset','16','--mbr-force-bootable',
         '-append_partition','2','0xef',fat,'-appended_part_as_gpt',
         '-c','boot.catalog','-b','boot/grub/i386-pc/eltorito.img',
         '-no-emul-boot','-boot-load-size','4','-boot-info-table','--grub2-boot-info',
         '-eltorito-alt-boot','-e','--interval:appended_partition_2:all::','-no-emul-boot',tree],stdout=subprocess.DEVNULL)
    report={'signed_ubuntu_efi_chain':True,'efi_components':rows,'secure_boot_tested':False,'bios_boot_image_preserved':True,'iso_sha256':sha(output),'iso_bytes':output.stat().st_size}
    (work/'secure-boot-build.json').write_text(json.dumps(report,indent=2)+'\n')
    return report

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--rootfs',type=Path,required=True);p.add_argument('--workdir',type=Path,required=True);a=p.parse_args();print(json.dumps(build(a.source,a.output,a.rootfs,a.workdir),indent=2))
if __name__=='__main__':main()
