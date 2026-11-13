"""
What a language says about following a request: which handlers, routers and apps
require a signed-in caller, and where a function's own inputs reach a dangerous call.
"""

from __future__ import annotations

import textwrap

from codelith.languages import registry


def facts(path: str, source: str):
    return registry.for_path(path).flow_facts(path, textwrap.dedent(source))


class TestPythonGuards:
    def test_a_dependency_a_decorator_and_an_alias(self) -> None:
        f = facts(
            "app/api.py",
            """
            Me = Annotated[User, Depends(get_current_admin)]
            DbSession = Annotated[Session, Depends(get_db)]

            @router.get("/a")
            def a(user=Depends(get_current_user)): ...

            @login_required
            def b(): ...

            @router.get("/c")
            def c(db: DbSession, me: Me): ...

            @router.get("/d")
            def d(q: str): ...
            """,
        )
        assert set(f.guards.handlers) == {"a", "b"}
        # `Me` says nothing by its name: it is known from what it wraps, in any file.
        assert set(f.guards.aliases) == {"Me"}
        assert "Me" in f.guards.uses["c"] and "d" not in f.guards.handlers

    def test_a_router_and_an_app_wide_guard(self) -> None:
        f = facts(
            "app/api.py",
            """
            router = APIRouter(prefix="/x", dependencies=[Depends(require_user)])
            open_router = APIRouter()
            app.add_middleware(AuthenticationMiddleware, backend=JWTBackend())
            """,
        )
        assert set(f.guards.routers) == {"router"}
        assert f.guards.app and "AuthenticationMiddleware" in f.guards.app

    def test_a_drf_view_with_permissions(self) -> None:
        f = facts("app/views.py", "class Orders(APIView):\n    permission_classes = [IsAuthenticated]\n")
        assert "Orders.*" in f.guards.handlers
        assert "Open.*" not in facts("app/views.py", "class Open(APIView):\n    permission_classes = [AllowAny]\n").guards.handlers


class TestPythonSinks:
    def test_sql_text_built_from_an_input_but_not_a_query_object(self) -> None:
        f = facts(
            "app/store.py",
            """
            def search(conn, term):
                sql = f"SELECT * FROM orders WHERE name = '{term}'"
                return conn.execute(sql)

            def find(db, oid):
                return db.execute(select(Order).where(Order.id == oid))
            """,
        )
        assert [(s.kind, s.function, s.line) for s in f.sinks] == [("sql", "search", 4)]

    def test_a_shell_only_through_a_shell(self) -> None:
        f = facts(
            "app/run.py",
            """
            def a(ref):
                subprocess.run(f"git log {ref}", shell=True)

            def b(ref):
                subprocess.run(["git", "log", ref])
            """,
        )
        assert [(s.kind, s.function) for s in f.sinks] == [("shell", "a")]

    def test_a_path_checked_to_stay_in_its_folder_is_not_a_sink(self) -> None:
        f = facts(
            "app/files.py",
            """
            def serve(name):
                return FileResponse(BASE / name)

            def serve_safely(name):
                p = (BASE / name).resolve()
                if not p.is_relative_to(BASE):
                    raise NotFound()
                return FileResponse(p)
            """,
        )
        assert [s.function for s in f.sinks] == ["serve"]

    def test_a_url_from_an_input_through_an_assignment(self) -> None:
        f = facts("app/fetch.py", "def fetch(url):\n    target = url.strip()\n    return requests.get(target, timeout=3)\n")
        assert [(s.kind, s.params) for s in f.sinks] == [("url", ["target"])]

    def test_request_data_logged_whole_but_not_one_field_of_it(self) -> None:
        f = facts(
            "app/x.py",
            "def a(body):\n    logger.info('got %s', body)\ndef b(params):\n    logger.warning('x', model=params['model'])\n",
        )
        assert [(s.kind, s.function) for s in f.sinks] == [("log", "a")]

    def test_the_session_and_the_caller_are_not_input(self) -> None:
        f = facts("app/x.py", "def f(db, user, q):\n    open(user.home)\n    open(q)\n")
        assert [s.line for s in f.sinks] == [3]


class TestPatterns:
    def test_typescript_router_guard_and_sinks(self) -> None:
        f = facts("src/api.ts", "router.use(requireAuth)\napp.get('/f', (req, res) => res.sendFile(req.query.p))\n")
        assert set(f.guards.routers) == {"router"}
        assert [s.kind for s in f.sinks] == ["file"]

    def test_java_method_guard_and_spring_security(self) -> None:
        f = facts("A.java", '@PreAuthorize("hasRole(ADMIN)")\n@GetMapping("/users")\npublic List<User> listUsers() { }\n')
        assert set(f.guards.handlers) == {"listUsers"}
        assert facts("S.java", "@EnableWebSecurity\nclass S {}\n").guards.app

    def test_go_middleware(self) -> None:
        assert facts("main.go", "r.Use(middleware.JWTAuth)\n").guards.app
