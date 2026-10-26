//! EOS 4.71-beta patches. Each contains only the bytes that differ from stock EOS 4.70 (all written for
//! this project); it is applied to the user's own 4.70 image and both ends are checked by SHA-256.
//!
//! Format (big-endian): b"E4PATCH1" or b"E4PATCH2", sha256(stock) 32, sha256(patched) 32, u32 image
//! length, u8 name length, name, u32 count, then:
//! * version 1: per range u32 offset, u32 length, bytes.
//! * version 2: ops applied in order: u8 0 (data), u32 offset, u32 length, bytes; or u8 1 (copy),
//!   u32 offset, u32 length, u32 source offset: bytes taken from the user's own 4.70 image. Code of
//!   E-mu's that a build moves (build 3 relocates the E-mu filter code) is copied, never shipped.
//! Made by tools/make_patch.py (`--v2` for version 2).

use sha2::{Digest, Sha256};

/// EOS 4.71-beta (beta1).
pub const BETA1: &[u8] = include_bytes!("../data/eos471beta.e4p");
/// EOS 4.71-beta2 build 2.
pub const BETA2: &[u8] = include_bytes!("../data/eos471beta2.e4p");
/// EOS 4.71-beta2 build 3 (version 2 format).
pub const BUILD3: &[u8] = include_bytes!("../data/eos471beta2b3.e4p");

/// Which OS to build from the user's EOS 4.70.
#[derive(PartialEq, Eq, Clone, Copy, Debug)]
pub enum Version {
    Build3,
    Beta2,
    Beta1,
    Original,
}

impl Version {
    /// The embedded patch for this version (none for the original 4.70).
    pub fn patch(self) -> Option<&'static [u8]> {
        match self {
            Version::Build3 => Some(BUILD3),
            Version::Beta2 => Some(BETA2),
            Version::Beta1 => Some(BETA1),
            Version::Original => None,
        }
    }
}

/// One step of a patch: write our bytes, or copy bytes from the user's own 4.70 image.
pub enum Op<'a> {
    Data(usize, &'a [u8]),
    Copy { off: usize, len: usize, src: usize },
}

pub struct Patch<'a> {
    pub stock_sha: &'a [u8],
    pub out_sha: &'a [u8],
    pub len: usize,
    pub name: String,
    pub ops: Vec<Op<'a>>,
}

fn u32at(b: &[u8], o: usize) -> usize {
    u32::from_be_bytes([b[o], b[o + 1], b[o + 2], b[o + 3]]) as usize
}

pub fn parse(p: &[u8]) -> Result<Patch<'_>, String> {
    let bad = || "bad patch data".to_string();
    if p.len() < 81 || (&p[..8] != b"E4PATCH1" && &p[..8] != b"E4PATCH2") {
        return Err(bad());
    }
    let v2 = &p[..8] == b"E4PATCH2";
    let len = u32at(p, 72);
    let nl = p[76] as usize;
    if 77 + nl + 4 > p.len() {
        return Err(bad());
    }
    let name = String::from_utf8_lossy(&p[77..77 + nl]).to_string();
    let mut o = 77 + nl;
    let count = u32at(p, o);
    o += 4;
    let mut ops = Vec::with_capacity(count.min(1 << 16));
    for _ in 0..count {
        let kind = if v2 {
            if o >= p.len() {
                return Err(bad());
            }
            o += 1;
            p[o - 1]
        } else {
            0
        };
        if o + 8 > p.len() {
            return Err(bad());
        }
        let off = u32at(p, o);
        let l = u32at(p, o + 4);
        o += 8;
        match kind {
            0 => {
                if o + l > p.len() || off + l > len {
                    return Err(bad());
                }
                ops.push(Op::Data(off, &p[o..o + l]));
                o += l;
            }
            1 => {
                if o + 4 > p.len() {
                    return Err(bad());
                }
                let src = u32at(p, o);
                o += 4;
                if off + l > len || src + l > len {
                    return Err(bad());
                }
                ops.push(Op::Copy { off, len: l, src });
            }
            _ => return Err(bad()),
        }
    }
    if o != p.len() {
        return Err(bad());
    }
    Ok(Patch { stock_sha: &p[8..40], out_sha: &p[40..72], len, name, ops })
}

pub fn sha256(d: &[u8]) -> Vec<u8> {
    Sha256::digest(d).to_vec()
}

/// Checks that `img` is exactly the stock EOS 4.70 image the patches were made for.
pub fn check_stock(img: &[u8]) -> Result<(), String> {
    let p = parse(BETA1)?;
    if img.len() != p.len || sha256(img) != p.stock_sha {
        return Err("this is not the original E-mu EOS 4.70 image (SHA-256 mismatch)".into());
    }
    Ok(())
}

/// Applies a patch to stock 4.70 and verifies the result.
pub fn apply(stock: &[u8], patch: &[u8]) -> Result<Vec<u8>, String> {
    check_stock(stock)?;
    let p = parse(patch)?;
    if p.stock_sha != parse(BETA1)?.stock_sha {
        return Err("patch was not made for EOS 4.70".into());
    }
    let mut img = stock.to_vec();
    for op in &p.ops {
        match *op {
            Op::Data(off, data) => img[off..off + data.len()].copy_from_slice(data),
            Op::Copy { off, len, src } => img[off..off + len].copy_from_slice(&stock[src..src + len]),
        }
    }
    if sha256(&img) != p.out_sha {
        return Err(format!("patched image does not match {} (SHA-256)", p.name));
    }
    crate::image::verify(&img)?;
    Ok(img)
}

/// (name, steps, our bytes, bytes copied from the user's own 4.70) of a patch.
pub fn info(patch: &[u8]) -> (String, usize, usize, usize) {
    let p = parse(patch).expect("embedded patch");
    let (mut data, mut copied) = (0, 0);
    for op in &p.ops {
        match op {
            Op::Data(_, d) => data += d.len(),
            Op::Copy { len, .. } => copied += len,
        }
    }
    (p.name, p.ops.len(), data, copied)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn embedded_patches() {
        let (a, b, c) = (parse(BETA1).unwrap(), parse(BETA2).unwrap(), parse(BUILD3).unwrap());
        assert!(a.stock_sha == b.stock_sha && b.stock_sha == c.stock_sha, "all apply to the same EOS 4.70");
        assert!(a.len == b.len && b.len == c.len);
        assert_eq!(a.name, "EOS 4.71-beta");
        assert_eq!(b.name, "EOS 4.71-beta2 build 2");
        assert_eq!(c.name, "EOS 4.71-beta2 build 3");
        for p in [&a, &b, &c] {
            let mut last = 0;
            for op in &p.ops {
                let (off, n) = match op {
                    Op::Data(off, d) => (*off, d.len()),
                    Op::Copy { off, len, .. } => (*off, *len),
                };
                assert!(off >= last && n > 0, "steps sorted, non-overlapping and non-empty");
                last = off + n;
            }
        }
        assert!(c.ops.iter().any(|o| matches!(o, Op::Copy { .. })), "build 3 copies E-mu code, never ships it");
    }

    #[test]
    fn rejects_truncated_patches() {
        for p in [BETA1, BETA2, BUILD3] {
            for cut in [p.len() - 1, p.len() / 2, 100] {
                assert!(parse(&p[..cut]).is_err(), "truncated patch accepted");
            }
        }
    }
}
