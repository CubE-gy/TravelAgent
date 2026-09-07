from app.schemas.trip_conversation import TripMessageCreate


def test_conversation_context_keeps_latest_turns_within_eight_thousand_characters() -> None:
    request = TripMessageCreate(
        message="继续",
        expected_revision=0,
        conversation_context=[
            {"role": "user", "content": "a" * 1000},
            {"role": "assistant", "content": "b" * 1000},
            {"role": "user", "content": "c" * 1000},
            {"role": "assistant", "content": "d" * 1000},
            {"role": "user", "content": "e" * 1000},
            {"role": "assistant", "content": "f" * 1000},
            {"role": "user", "content": "g" * 1000},
            {"role": "assistant", "content": "h" * 1000},
            {"role": "user", "content": "i" * 1000},
        ],
    )

    assert len(request.conversation_context) == 8
    assert request.conversation_context[0].content == "b" * 1000
    assert sum(len(item.content) for item in request.conversation_context) == 8000
