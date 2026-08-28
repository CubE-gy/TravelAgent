import pytest
from pydantic import BaseModel, ValidationError

from app.services.llm_provider import LlmMessage, LlmMessageRole, LlmProvider, MockLlmProvider


class ExtractedDestination(BaseModel):
    destination: str


class FakeLlmProvider:
    def generate_structured(
        self,
        messages: list[LlmMessage],
        response_model: type[ExtractedDestination],
    ) -> ExtractedDestination:
        return response_model(destination=messages[-1].content)


@pytest.mark.parametrize(
    "role",
    [LlmMessageRole.SYSTEM, LlmMessageRole.USER, LlmMessageRole.ASSISTANT],
)
def test_llm_message_accepts_supported_roles_and_normalizes_content(
    role: LlmMessageRole,
) -> None:
    message = LlmMessage(role=role, content="  请提取旅行信息  ")

    assert message.role is role
    assert message.content == "请提取旅行信息"


def test_llm_message_rejects_blank_content() -> None:
    with pytest.raises(ValidationError, match="content must not be blank"):
        LlmMessage(role=LlmMessageRole.USER, content="   ")


def test_fake_provider_uses_the_unified_structured_call_contract() -> None:
    provider = FakeLlmProvider()
    messages = [LlmMessage(role=LlmMessageRole.USER, content="我想去北京")]

    result = provider.generate_structured(messages, ExtractedDestination)

    assert isinstance(provider, LlmProvider)
    assert result == ExtractedDestination(destination="我想去北京")


def test_mock_provider_returns_explicit_test_data_without_network_access() -> None:
    provider = MockLlmProvider(response_data={"destination": "北京"})
    messages = [LlmMessage(role=LlmMessageRole.USER, content="我想去北京")]

    result = provider.generate_structured(messages, ExtractedDestination)

    assert result == ExtractedDestination(destination="北京")
    assert provider.calls == [(messages, ExtractedDestination)]
