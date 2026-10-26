//! Command-line check: EOS470.EXE -> 4.71-beta2 build 3 (or build 2, 4.71-beta, or 4.70) -> .syx, verified by the
//! loader simulation. usage: check EOS470.EXE OUT.syx [--build2 | --beta1 | --original]
fn main() {
    let a: Vec<String> = std::env::args().collect();
    let data = std::fs::read(&a[1]).expect("read input");
    use eos_core::patch::Version;
    let v = if a.iter().any(|x| x == "--original") {
        Version::Original
    } else if a.iter().any(|x| x == "--beta1") {
        Version::Beta1
    } else if a.iter().any(|x| x == "--build2") {
        Version::Beta2
    } else {
        Version::Build3
    };
    let (img, name) = eos_core::build_image(&data, v).unwrap_or_else(|e| panic!("{e}"));
    let msgs = eos_core::filedump::messages_for_image(&img).unwrap_or_else(|e| panic!("{e}"));
    std::fs::write(&a[2], eos_core::filedump::to_syx(&msgs)).expect("write");
    println!("{}: '{}', {} messages, checksum {:08x}", a[2], name, msgs.len(), eos_core::image::csum(&img));
}
