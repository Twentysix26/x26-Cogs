from ..core.warden.enums import Action, Condition, Event
from ..enums import Rank
from ..core.warden.constants import ALLOWED_ACTIONS, ALLOWED_CONDITIONS, CONDITIONS_PARAM_TYPE, ACTIONS_PARAM_TYPE
from ..core.warden.constants import CONDITIONS_ANY_CONTEXT, CONDITIONS_USER_CONTEXT, CONDITIONS_MESSAGE_CONTEXT
from ..core.warden.constants import ACTIONS_ANY_CONTEXT, ACTIONS_USER_CONTEXT, ACTIONS_MESSAGE_CONTEXT, ACTIONS_ARGS_N
from ..core.warden.rule import WardenRule
from ..exceptions import InvalidRule
from .wd_sample_rules import (DYNAMIC_RULE, TUTORIAL_SIMPLE_RULE, TUTORIAL_COMPLEX_RULE,
                              INVALID_RANK, INVALID_EVENT, TUTORIAL_PRIORITY_RULE, INVALID_PRIORITY)
import pytest

def test_check_constants_consistency():
    def x_contains_only_y(x, y):
        for element in x:
            if not isinstance(element, y):
                return False
        return True

    for condition in Condition:
        assert condition in CONDITIONS_PARAM_TYPE

    for action in Action:
        assert action in ACTIONS_PARAM_TYPE

    i = 0
    print("Checking if conditions are in one and only one context...")
    for condition in Condition:
        print(f"Checking {condition.value}...")
        if condition in CONDITIONS_ANY_CONTEXT:
            i += 1

        if condition in CONDITIONS_USER_CONTEXT:
            i += 1

        if condition in CONDITIONS_MESSAGE_CONTEXT:
            i += 1

        assert i == 1
        i = 0

    i = 0
    print("Checking if actions are in one and only one context...")
    for action in Action:
        print(f"Checking {action.value}...")
        if action in ACTIONS_ANY_CONTEXT:
            i += 1

        if action in ACTIONS_USER_CONTEXT:
            i += 1

        if action in ACTIONS_MESSAGE_CONTEXT:
            i += 1

        assert i == 1
        i = 0

    assert x_contains_only_y(CONDITIONS_ANY_CONTEXT, Condition)
    assert x_contains_only_y(CONDITIONS_USER_CONTEXT, Condition)
    assert x_contains_only_y(CONDITIONS_MESSAGE_CONTEXT, Condition)
    assert x_contains_only_y(ACTIONS_ANY_CONTEXT, Action)
    assert x_contains_only_y(ACTIONS_USER_CONTEXT, Action)
    assert x_contains_only_y(ACTIONS_MESSAGE_CONTEXT, Action)

def test_rule_parsing():
    with pytest.raises(InvalidRule, match=r".*rank.*"):
        WardenRule(INVALID_RANK)
    with pytest.raises(InvalidRule, match=r".*event.*"):
        WardenRule(INVALID_EVENT)
    with pytest.raises(InvalidRule, match=r".*number.*"):
        WardenRule(INVALID_PRIORITY)

    WardenRule(TUTORIAL_SIMPLE_RULE)
    WardenRule(TUTORIAL_PRIORITY_RULE)

    rule = WardenRule(TUTORIAL_COMPLEX_RULE)
    assert isinstance(rule.rank, Rank)
    assert rule.name and isinstance(rule.name, str)
    assert rule.raw_rule and isinstance(rule.raw_rule, str)
    assert rule.events and isinstance(rule.events, list)
    assert rule.conditions and isinstance(rule.conditions, list)
    assert rule.actions and isinstance(rule.actions, list)

    # Dynamic rule generation to test every possible
    # combination of event, conditions and actions

    print("Dynamic rule generation...")
    for event in Event:
        gen_conditions = []
        gen_actions = []
        for condition in ALLOWED_CONDITIONS[event]:
            if str in CONDITIONS_PARAM_TYPE[condition]:
                gen_conditions.append(f'    - {condition.value}: test')
            elif int in CONDITIONS_PARAM_TYPE[condition]:
                gen_conditions.append(f'    - {condition.value}: 26')
            elif list in CONDITIONS_PARAM_TYPE[condition]:
                gen_conditions.append(f'    - {condition.value}: ["*"]')
            elif bool in CONDITIONS_PARAM_TYPE[condition]:
                gen_conditions.append(f'    - {condition.value}: true')
            elif None in CONDITIONS_PARAM_TYPE[condition]:
                gen_conditions.append(f'    - {condition.value}:')
            else:
                raise ValueError("Unhandled data type in allowed conditions param types: "
                                 f"{CONDITIONS_PARAM_TYPE[condition]}")

        for action in ALLOWED_ACTIONS[event]:
            if str in ACTIONS_PARAM_TYPE[action]:
                gen_actions.append(f'    - {action.value}: test')
            elif int in ACTIONS_PARAM_TYPE[action]:
                gen_actions.append(f'    - {action.value}: 26')
            elif list in ACTIONS_PARAM_TYPE[action]:
                args_n = ACTIONS_ARGS_N.get(action, 1)
                args = ['"*"' for i in range(args_n)]
                gen_actions.append(f'    - {action.value}: [{", ".join(args)}]')
            elif bool in ACTIONS_PARAM_TYPE[action]:
                gen_actions.append(f'    - {action.value}: true')
            elif None in ACTIONS_PARAM_TYPE[action]:
                gen_actions.append(f'    - {action.value}:')
            else:
                raise ValueError("Unhandled data type in allowed actions param types: "
                                 f"{ACTIONS_PARAM_TYPE[action]}")

        raw = DYNAMIC_RULE.format(event=event.value,
                                  conditions="\n".join(gen_conditions),
                                  actions="\n".join(gen_actions))

        print(f"Testing {event.value} with {len(gen_conditions)} conditions and "
              f"{len(gen_actions)} actions.")

        WardenRule(raw)