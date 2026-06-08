from string import Template


class PromptTemplate:
    def __init__(self, system: str, user: str) -> None:
        self._system = system
        self._user = user

    def render(self, **kwargs) -> list[dict]:
        system = Template(self._system).safe_substitute(**kwargs)
        user = Template(self._user).safe_substitute(**kwargs)
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
