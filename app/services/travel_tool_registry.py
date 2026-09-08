"""Look up the tool an Agent decision selected, by name."""

from app.services.travel_tool import TravelTool


class UnknownTravelToolError(KeyError):
    """The decision selected a tool the registry has not been configured with."""


class TravelToolRegistry:
    """A small, read-mostly index of available travel tools."""

    def __init__(self, tools: list[TravelTool]) -> None:
        self._tools: dict[str, TravelTool] = {tool.name: tool for tool in tools}

    def get(self, name: str) -> TravelTool:
        if name not in self._tools:
            raise UnknownTravelToolError(f"unknown travel tool: {name}")
        return self._tools[name]

    def has(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def all(self) -> list[TravelTool]:
        return list(self._tools.values())

    def describe_for_prompt(self) -> str:
        """Render the schema list for prompts that want to name available tools."""
        return "\n".join(f"- {tool.name}: {tool.description}" for tool in self._tools.values())
