"""Carry one bounded draft through optional editor panels and input restoration."""

from dataclasses import asdict

from . import navigation as nav


def update_draft(state: dict, draft) -> None:
    """Update only frames belonging to this draft, never another conversation."""
    frames = [state, state.get('_parent_frame', {}), *state.get('_stack', [])]
    for frame in frames:
        previous = frame.get('forum_draft', {})
        if previous.get('token') == draft.token and frame.get('menu') in (
            {nav.COMPOSER, nav.EXTRAS, nav.POLL_EDITOR, nav.ATTACHMENT} | nav.INPUT_IDS
        ):
            frame['forum_draft'] = asdict(draft)
