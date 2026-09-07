from jace.tools.base import ToolDefinition


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition, *, replace: bool = False) -> None:
        if tool.name in self._tools and not replace:
            raise ValueError(f"Tool '{tool.name}' is already registered.")
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def all(self) -> list[ToolDefinition]:
        return sorted(
            self._tools.values(),
            key=lambda tool: (tool.category.lower(), tool.label.lower()),
        )

    def schemas(self, allowed_names: set[str] | None = None) -> list[dict]:
        tools = self.all()
        if allowed_names is not None:
            tools = [tool for tool in tools if tool.name in allowed_names]
        return [tool.ollama_schema() for tool in tools]


registry = ToolRegistry()
