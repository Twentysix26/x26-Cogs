TUTORIAL_SIMPLE_RULE = """
    name: spiders-are-spooky
    rank: 1
    event: on-message
    if:
    - message-matches-any: ["*spider*"]
    do:
    - delete-user-message:
"""

TUTORIAL_COMPLEX_RULE = """
    name: spiders-are-spooky
    rank: 1
    event: on-message
    if:
    - if-any:
        - username-matches-any: ["*spider*"]
        - message-matches-any: ["*spider*"]
        - nickname-matches-any: ["*spider*"]
    - if-not:
        - user-joined-less-than: 2
        - is-staff: true
    do:
    - ban-user-and-delete: 1
    - send-mod-log: "Usage of the S word is not welcome in this community. Begone, $user."
"""

TUTORIAL_PRIORITY_RULE = """
    name: always-first
    rank: 1
    priority: 1
    event: on-message
    if:
    - message-matches-any: ["*"]
    do:
    - send-to-monitor: "I'm 1st!"
"""

INVALID_PRIORITY = """
    name: always-first
    rank: 1
    priority: first
    event: on-message
    if:
    - message-matches-any: ["*"]
    do:
    - send-to-monitor: "I'm 1st!"
"""

INVALID_RANK = """
    name: test
    rank: 8
    event: on-message
    if:
        - messages-matches-any: ["*"]
    do:
        - no-op:
"""

INVALID_EVENT = """
    name: test
    rank: 4
    event: xxxx
    if:
        - messages-matches-any: ["*"]
    do:
        - no-op:
"""

INVALID_PERIODIC_MISSING_RUN_EVERY = """
    name: per
    rank: 2
    event: periodic
    if:
        - username-matches-any: ["abcd"]
    do:
        - no-op:
"""

INVALID_PERIODIC_MISSING_EVENT = """
    name: per
    rank: 2
    run-every: 2 hours
    event: on-user-join
    if:
        - username-matches-any: ["abcd"]
    do:
        - no-op:
"""

VALID_MIXED_RULE = """
    name: spiders-are-spooky
    rank: 1
    event: [on-message, on-user-join]
    if:
    - username-matches-any: ["*spider*"]
    do:
    - set-user-nickname: bunny
"""

INVALID_MIXED_RULE_CONDITION = """
    name: spiders-are-spooky
    rank: 1
    event: [on-message, on-user-join]
    if:
    - message-matches-any: ["*spider*"]
    do:
    - set-user-nickname: bunny
"""

INVALID_MIXED_RULE_ACTION = """
    name: spiders-are-spooky
    rank: 1
    event: [on-message, on-user-join]
    if:
    - username-matches-any: ["*spider*"]
    do:
    - delete-user-message:
"""

DYNAMIC_RULE = """
    name: test
    rank: 3
    event: {event}
    if:
{conditions}
    do:
{actions}
"""

DYNAMIC_RULE_PERIODIC = """
    name: test
    rank: 3
    run-every: 15 minutes
    event: {event}
    if:
{conditions}
    do:
{actions}
"""

CONDITION_TEST_POSITIVE = """
    name: positive
    rank: 1
    event: on-user-join
    if:
    - if-any:
        - username-matches-any: ["Twentysix"]
        - nickname-matches-any: ["*spider*"]
    - if-not:
        - username-matches-any: ["xxxxxxxxx"]
    do:
    - no-op:
"""

CONDITION_TEST_NEGATIVE = """
    name: negative
    rank: 1
    event: on-user-join
    if:
    - if-all:
        - username-matches-any: ["Twentysix"]
    - if-not:
        - user-id-matches-any: [852499907842801726]
    do:
    - no-op:
"""

INCREASE_HEATPOINTS = """
    name: increase
    rank: 1
    event: on-message
    if:
    - if-any:
        - message-matches-any: ["increase"]
    do:
    - add-user-heatpoint: 9m
    - add-user-heatpoints: [1, 9m]
    - add-channel-heatpoint: 9m
    - add-channel-heatpoints: [5, 4m]
    - add-custom-heatpoint: ["test", 50m]
    - add-custom-heatpoints: ["test", 12, 50m]
"""

CHECK_HEATPOINTS = """
    name: check
    rank: 1
    event: on-message
    if:
        - user-heat-is: 2
        - channel-heat-is: 6
        - user-heat-more-than: 0
        - channel-heat-more-than: 0
        - custom-heat-is: ["test", 13]
        - custom-heat-more-than: ["test", 5]
    do:
        - no-op:
"""

EMPTY_HEATPOINTS = """
    name: empty
    rank: 1
    event: on-message
    if:
        - message-matches-any: ["*"]
    do:
        - empty-user-heat:
        - empty-channel-heat:
        - empty-custom-heat: "test"
"""

CHECK_EMPTY_HEATPOINTS = """
    name: check-empty
    rank: 1
    event: on-message
    if:
        - user-heat-is: 0
        - channel-heat-is: 0
        - custom-heat-is: ["test", 0]
    do:
        - no-op:
"""
