std_msgs/Header header
string episode_id
uint64 sequence_id

# Longitudinal linear velocity along base_link x-axis (m/s)
float32 linear_velocity

# Angular velocity around base_link z-axis, positive counter-clockwise / left turn (rad/s)
float32 angular_velocity

# Task completion and stopping probability [0.0, 1.0]
float32 stop_probability

# Monotonic clock duration from tensor ready to model output (ms)
float32 inference_latency_ms

# Action validity flag (false if NaN, Inf, out-of-bound stop_prob, or calculation failure)
bool valid

# Traceable model architecture and weights identifier
string model_version
