std_msgs/Header header
string episode_id
uint64 action_sequence_id

# Safety layer flags
bool command_accepted
bool command_modified
bool emergency_stop
bool policy_timeout
bool human_takeover

# Stable reason code enum for metric calculation and diagnosis
uint8 reason_code
string reason_detail

# Reason codes
uint8 REASON_NORMAL = 0
uint8 REASON_SPEED_LIMIT = 1
uint8 REASON_ACCELERATION_LIMIT = 2
uint8 REASON_INVALID_ACTION = 3
uint8 REASON_ACTION_EXPIRED = 4
uint8 REASON_POLICY_TIMEOUT = 5
uint8 REASON_OBSTACLE_STOP = 6
uint8 REASON_HUMAN_TAKEOVER = 7
uint8 REASON_ARBITER_REJECTED = 8
uint8 REASON_INTERNAL_ERROR = 9
uint8 REASON_EPISODE_INACTIVE = 10
uint8 REASON_EMERGENCY_STOP = 11
