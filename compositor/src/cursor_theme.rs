//! Load one cached, static frame from an installed Xcursor theme.
pub struct CursorImage {pub pixels:Vec<u8>,pub width:i32,pub height:i32,pub xhot:i32,pub yhot:i32}
pub fn load(light:bool)->CursorImage {
    let names=if light { ["Bibata-Modern-Classic","DMZ-Black"] }else{["Bibata-Modern-Ice","DMZ-White"]};
    for name in names {
        let path=format!("/usr/share/icons/{name}/cursors/left_ptr");
        if let Ok(bytes)=std::fs::read(path) {if let Some(image)=parse(&bytes){return image;}}
    }
    let mut pixels=vec![0;16*24*4];
    for y in 0..21 {for x in 0..=y/2 {let i=(y*16+x)*4;let border=x==0||x==y/2||y==20;let c=if border==light {245}else{15};pixels[i..i+4].copy_from_slice(&[c,c,c,255]);}}
    CursorImage{pixels,width:16,height:24,xhot:0,yhot:0}
}
fn parse(bytes:&[u8])->Option<CursorImage>{
    if bytes.len()>4_000_000 || bytes.get(..4)?!=b"Xcur" {return None;}
    let word=|at:usize|->Option<u32>{Some(u32::from_le_bytes(bytes.get(at..at+4)?.try_into().ok()?))};
    let header=word(4)? as usize;let count=word(12)?.min(1024) as usize;
    let mut choices=Vec::new();
    for i in 0..count {let at=header+i*12;if word(at)?==0xfffd0002 {choices.push((word(at+4)?.abs_diff(24),word(at+8)? as usize));}}
    choices.sort_by_key(|v|v.0);
    for (_,at) in choices {let w=word(at+16)? as usize;let h=word(at+20)? as usize;let x=word(at+24)?;let y=word(at+28)?;let start=at+word(at)? as usize;
        if w>0 && h>0 && w<=128 && h<=128 && x<w as u32 && y<h as u32 {let pixels=bytes.get(start..start+w*h*4)?.to_vec();return Some(CursorImage{pixels,width:w as i32,height:h as i32,xhot:x as i32,yhot:y as i32});}
    }None
}
#[cfg(test)] mod tests {#[test]fn installed_themes_are_bounded_and_distinct(){let dark=super::load(false);let light=super::load(true);assert!(dark.width<=128&&light.width<=128);assert_ne!(dark.pixels,light.pixels);}#[test]fn malformed_data_is_rejected(){assert!(super::parse(b"bad").is_none());}}
