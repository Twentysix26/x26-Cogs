from ..core.warden.enums import Action, Condition, Event
from ..enums import Rank
from ..core.warden.constants import ALLOWED_ACTIONS, ALLOWED_CONDITIONS, CONDITIONS_PARAM_TYPE, ACTIONS_PARAM_TYPE
from ..core.warden.constants import CONDITIONS_ANY_CONTEXT, CONDITIONS_USER_CONTEXT, CONDITIONS_MESSAGE_CONTEXT
from ..core.warden.constants import ACTIONS_ANY_CONTEXT, ACTIONS_USER_CONTEXT, ACTIONS_MESSAGE_CONTEXT, ACTIONS_ARGS_N
from ..core.warden.constants import CONDITIONS_ARGS_N
from ..core.warden.rule import WardenRule
from ..exceptions import InvalidRule
from .wd_sample_rules import (CHECK_EMPTY_HEATPOINTS, CHECK_HEATPOINTS, DYNAMIC_RULE, DYNAMIC_RULE_PERIODIC, EMPTY_HEATPOINTS,
                              INCREASE_HEATPOINTS, TUTORIAL_SIMPLE_RULE, TUTORIAL_COMPLEX_RULE,
                              INVALID_RANK, INVALID_EVENT, TUTORIAL_PRIORITY_RULE, INVALID_PRIORITY,
                              INVALID_PERIODIC_MISSING_EVENT, INVALID_PERIODIC_MISSING_RUN_EVERY, VALID_MIXED_RULE,
                              INVALID_MIXED_RULE_CONDITION, INVALID_MIXED_RULE_ACTION, CONDITION_TEST_POSITIVE,
                              CONDITION_TEST_NEGATIVE)
from datetime import datetime
import pytest

class FakeGuild:
    id = 852499907842801727

FAKE_GUILD = FakeGuild()

class FakeChannel:
    id = 852499907842801728
    name = "fake"
    guild = FAKE_GUILD
    category = None
    mention = "<@852499907842801728>"

FAKE_CHANNEL = FakeChannel()

class FakeUser:
    nick = None
    name = "Twentysix"
    id = 852499907842801726
    guild = FAKE_GUILD
    mention = "<@852499907842801726>"
    created_at = datetime.utcnow()
    joined_at = datetime.utcnow()

FAKE_USER = FakeUser()

class FakeMessage:
    id = 852499907842801729
    guild = FAKE_GUILD
    channel = FAKE_CHANNEL
    author = FAKE_USER
    content = clean_content = "increase"
    created_at = datetime.utcnow()
    jump_url = ""
    attachments = []

FAKE_MESSAGE = FakeMessage()

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

@pytest.mark.asyncio
async def test_rule_parsing():
    with pytest.raises(InvalidRule, match=r".*rank.*"):
        await WardenRule().parse(INVALID_RANK, cog=None)
    with pytest.raises(InvalidRule, match=r".*event.*"):
        await WardenRule().parse(INVALID_EVENT, cog=None)
    with pytest.raises(InvalidRule, match=r".*number.*"):
        await WardenRule().parse(INVALID_PRIORITY, cog=None)
    with pytest.raises(InvalidRule, match=r".*'run-every' parameter is mandatory.*"):
        await WardenRule().parse(INVALID_PERIODIC_MISSING_RUN_EVERY, cog=None)
    with pytest.raises(InvalidRule, match=r".*'periodic' event must be specified.*"):
        await WardenRule().parse(INVALID_PERIODIC_MISSING_EVENT, cog=None)
    with pytest.raises(InvalidRule, match=r".*Condition `message-matches-any` not allowed*"):
        await WardenRule().parse(INVALID_MIXED_RULE_CONDITION, cog=None)
    with pytest.raises(InvalidRule, match=r".*Action `delete-user-message` not allowed*"):
        await WardenRule().parse(INVALID_MIXED_RULE_ACTION, cog=None)

    await WardenRule().parse(TUTORIAL_SIMPLE_RULE, cog=None)
    await WardenRule().parse(TUTORIAL_PRIORITY_RULE, cog=None)
    await WardenRule().parse(VALID_MIXED_RULE, cog=None)

    rule = WardenRule()
    await rule.parse(TUTORIAL_COMPLEX_RULE, cog=None)
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
                args_n = CONDITIONS_ARGS_N.get(condition, 1)
                args = ['"*"' for i in range(args_n)]
                gen_conditions.append(f'    - {condition.value}: [{", ".join(args)}]')
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

        if event != Event.Periodic:
            raw = DYNAMIC_RULE.format(event=event.value,
                                      conditions="\n".join(gen_conditions),
                                      actions="\n".join(gen_actions))
        else:
            raw = DYNAMIC_RULE_PERIODIC.format(event=event.value,
                                               conditions="\n".join(gen_conditions),
                                               actions="\n".join(gen_actions))

        print(f"Testing {event.value} with {len(gen_conditions)} conditions and "
              f"{len(gen_actions)} actions.")

        await WardenRule().parse(raw, cog=None)

@pytest.mark.asyncio
async def test_rule_cond_eval():
    rule = WardenRule()
    await rule.parse(CONDITION_TEST_POSITIVE, cog=None)
    assert bool(await rule.satisfies_conditions(
        cog=None,
        rank=Rank.Rank1,
        guild=FAKE_GUILD,
        user=FAKE_USER)) is True

    rule = WardenRule()
    await rule.parse(CONDITION_TEST_NEGATIVE, cog=None)
    assert bool(await rule.satisfies_conditions(
        cog=None,
        rank=Rank.Rank1,
        guild=FAKE_GUILD,
        user=FAKE_USER)) is False

    ##### Sandbox store
    rule = WardenRule()
    await rule.parse(CHECK_HEATPOINTS, cog=None)
    assert bool(await rule.satisfies_conditions(
        cog=None,
        rank=Rank.Rank1,
        guild=FAKE_GUILD,
        message=FAKE_MESSAGE)) is False

    rule = WardenRule()
    await rule.parse(INCREASE_HEATPOINTS, cog=None)
    assert bool(await rule.satisfies_conditions(
        cog=None,
        rank=Rank.Rank1,
        guild=FAKE_GUILD,
        message=FAKE_MESSAGE)) is True
    await rule.do_actions(cog=None,
        guild=FAKE_GUILD,
        message=FAKE_MESSAGE)

    rule = WardenRule()
    await rule.parse(CHECK_HEATPOINTS, cog=None)
    assert bool(await rule.satisfies_conditions(
        cog=None,
        rank=Rank.Rank1,
        guild=FAKE_GUILD,
        message=FAKE_MESSAGE)) is True
    ##############

    ##### Prod store
    rule = WardenRule()
    await rule.parse(CHECK_HEATPOINTS, cog=None)
    assert bool(await rule.satisfies_conditions(
        cog=None,
        rank=Rank.Rank1,
        guild=FAKE_GUILD,
        message=FAKE_MESSAGE,
        debug=True)) is False

    rule = WardenRule()
    await rule.parse(INCREASE_HEATPOINTS, cog=None)
    assert bool(await rule.satisfies_conditions(
        cog=None,
        rank=Rank.Rank1,
        guild=FAKE_GUILD,
        message=FAKE_MESSAGE,
        debug=True)) is True
    await rule.do_actions(cog=None,
        guild=FAKE_GUILD,
        message=FAKE_MESSAGE,
        debug=True)

    rule = WardenRule()
    await rule.parse(CHECK_HEATPOINTS, cog=None)
    assert bool(await rule.satisfies_conditions(
        cog=None,
        rank=Rank.Rank1,
        guild=FAKE_GUILD,
        message=FAKE_MESSAGE,
        debug=True)) is True
    ##############

    rule = WardenRule()
    await rule.parse(EMPTY_HEATPOINTS, cog=None)
    assert bool(await rule.satisfies_conditions(
        cog=None,
        rank=Rank.Rank1,
        guild=FAKE_GUILD,
        message=FAKE_MESSAGE,
        debug=True)) is True
    await rule.do_actions(cog=None,
        guild=FAKE_GUILD,
        message=FAKE_MESSAGE,
        debug=True)

    rule = WardenRule()
    await rule.parse(CHECK_EMPTY_HEATPOINTS, cog=None)
    assert bool(await rule.satisfies_conditions(
        cog=None,
        rank=Rank.Rank1,
        guild=FAKE_GUILD,
        message=FAKE_MESSAGE,
        debug=True)) is True


    rule = WardenRule()
    await rule.parse(CHECK_EMPTY_HEATPOINTS, cog=None)
    assert bool(await rule.satisfies_conditions(
        cog=None,
        rank=Rank.Rank1,
        guild=FAKE_GUILD,
        message=FAKE_MESSAGE)) is False

    rule = WardenRule()
    await rule.parse(EMPTY_HEATPOINTS, cog=None)
    assert bool(await rule.satisfies_conditions(
        cog=None,
        rank=Rank.Rank1,
        guild=FAKE_GUILD,
        message=FAKE_MESSAGE)) is True
    await rule.do_actions(cog=None,
        guild=FAKE_GUILD,
        message=FAKE_MESSAGE)

    rule = WardenRule()
    await rule.parse(CHECK_EMPTY_HEATPOINTS, cog=None)
    assert bool(await rule.satisfies_conditions(
        cog=None,
        rank=Rank.Rank1,
        guild=FAKE_GUILD,
        message=FAKE_MESSAGE)) is True
