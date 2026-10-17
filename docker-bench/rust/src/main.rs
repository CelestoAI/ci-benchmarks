use clap::Parser;
use rayon::prelude::*;
use regex::Regex;

#[derive(Parser)]
struct Args { #[arg(long, default_value_t = 1000)] rows: usize }

fn main() {
    let args = Args::parse();
    let re = Regex::new(r"item-[0-9]+").unwrap();
    let matched: usize = (0..args.rows).into_par_iter()
        .filter(|i| re.is_match(&format!("item-{i}"))).count();
    assert_eq!(matched, args.rows);
    println!("{}", serde_json::json!({"matched": matched}));
}
