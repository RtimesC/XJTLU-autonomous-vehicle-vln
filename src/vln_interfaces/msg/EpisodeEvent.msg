std_msgs/Header header
string episode_id
uint64 action_sequence_id
uint8 event_type
string reason

# Events are emitted by the adapter after its own stop confirmation or when a
# policy explicitly reports a terminal failure.
uint8 EVENT_STOP_LATCH = 1
uint8 EVENT_POLICY_FAILED = 2
