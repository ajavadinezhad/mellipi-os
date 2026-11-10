//! Both workspace roots share one eased timeline and remain one output apart.
pub fn offsets(progress: f64, direction: f64, height: f64) -> (f64, f64) {
    let p = progress.clamp(0.0, 1.0);
    let eased = p * p * (3.0 - 2.0 * p);
    (
        -direction * eased * height,
        direction * (1.0 - eased) * height,
    )
}
#[cfg(test)]
mod tests {
    use super::offsets;
    #[test]
    fn roots_remain_exactly_one_output_apart_in_both_directions() {
        for direction in [-1.0, 1.0] {
            for step in 0..=100 {
                let (old, new) = offsets(step as f64 / 100.0, direction, 1080.0);
                assert!((new - old - direction * 1080.0).abs() < 0.000001);
            }
        }
    }
    #[test]
    fn endpoints_put_only_the_selected_workspace_at_origin() {
        for direction in [-1.0, 1.0] {
            assert_eq!(offsets(0.0, direction, 720.0), (0.0, direction * 720.0));
            assert_eq!(offsets(1.0, direction, 720.0), (-direction * 720.0, 0.0));
        }
    }
}
