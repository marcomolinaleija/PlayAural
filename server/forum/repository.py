"""Bounded forum queries using PlayAural's existing SQLite connection.

This repository never opens a competing database or commits a transaction.
Writes are orchestrated by ForumService within Database._transaction(), so
maintenance, backups, migration and account deletion share one authority.
"""

from contextlib import contextmanager
from typing import TYPE_CHECKING

from ..menu_pagination import PaginatedMenuPage, clamp_page
from .models import Category, Post, Topic, POSTS_PER_PAGE, TOPICS_PER_PAGE, PRIVATE_CATEGORY_ID
from .text import search_key

if TYPE_CHECKING:
    from ..persistence.database import Database


def _visible(author: str) -> str:
    return f"""NOT EXISTS (
        SELECT 1 FROM user_blocks b
        WHERE (b.blocker_id = :viewer AND b.blocked_id = {author})
           OR (b.blocked_id = :viewer AND b.blocker_id = {author})
    )"""


def _admitted(topic: str = 't') -> str:
    """Private membership is required even for administrators and former owners."""
    return f"""(
        (NOT EXISTS (SELECT 1 FROM forum_private_topics ft WHERE ft.topic_id = {topic}.id)
         AND {_visible(f'{topic}.author_uuid')})
        OR EXISTS (SELECT 1 FROM forum_private_members fm
                   WHERE fm.topic_id = {topic}.id AND fm.user_uuid = :viewer)
    )"""


class ForumRepository:
    def __init__(self, database: "Database"):
        self.database = database

    @property
    def connection(self):
        return self.database._conn

    @contextmanager
    def atomic(self):
        with self.database._transaction(immediate=True):
            yield

    def _topics_sql(self) -> str:
        return f"""
            SELECT t.*, COUNT(p.id) AS post_count,
                COALESCE(SUM(CASE WHEN p.id > COALESCE(r.last_post_id, 0)
                    THEN 1 ELSE 0 END), 0) AS unread_count,
                COALESCE(MAX(p.id), 0) AS last_post_id,
                COALESCE(MAX(p.created_at), t.created_at) AS last_activity,
                CASE WHEN s.user_uuid IS NULL THEN 0 ELSE 1 END AS bookmarked,
                EXISTS (SELECT 1 FROM forum_private_topics ft WHERE ft.topic_id = t.id) AS is_private
            FROM forum_topics t
            LEFT JOIN forum_posts p ON p.topic_id = t.id AND {_visible('p.author_uuid')}
            LEFT JOIN forum_read_positions r ON r.topic_id = t.id AND r.user_uuid = :viewer
            LEFT JOIN forum_bookmarks s ON s.topic_id = t.id AND s.user_uuid = :viewer
            WHERE {_admitted()}
            GROUP BY t.id
        """

    @staticmethod
    def _topic(row) -> Topic:
        return Topic(**{key: row[key] for key in Topic.__dataclass_fields__})

    @staticmethod
    def _post(row) -> Post:
        data = {key: row[key] for key in Post.__dataclass_fields__}
        if data["hidden"]:
            data["body"] = ""
        return Post(**data)

    def categories(self, viewer: str, *, language: str = 'es') -> list[Category]:
        rows = self.connection.execute(
            f"""SELECT c.id, c.name, c.description, c.revision, c.language, COUNT(t.id) AS topic_count FROM forum_categories c
                LEFT JOIN forum_topics t ON t.category_id = c.id AND {_visible('t.author_uuid')}
                    AND NOT EXISTS (SELECT 1 FROM forum_private_topics ft WHERE ft.topic_id = t.id)
                WHERE c.id != :private AND c.language = :language GROUP BY c.id ORDER BY c.position, c.id""",
            {"viewer": viewer, "private": PRIVATE_CATEGORY_ID, "language": language},
        ).fetchall()
        return [Category(**dict(row)) for row in rows]

    def has_category(self, category_id: str) -> bool:
        return self.connection.execute(
            "SELECT 1 FROM forum_categories WHERE id = ? AND id != ?", (category_id, PRIVATE_CATEGORY_ID),
        ).fetchone() is not None

    def category(self, category_id: str) -> Category | None:
        row = self.connection.execute(
            '''SELECT c.id, c.name, c.description, c.revision, c.language,
                      (SELECT COUNT(*) FROM forum_topics t WHERE t.category_id = c.id
                       AND NOT EXISTS (SELECT 1 FROM forum_private_topics ft WHERE ft.topic_id = t.id)) AS topic_count
               FROM forum_categories c WHERE c.id = ? AND c.id != ?''',
            (category_id, PRIVATE_CATEGORY_ID),
        ).fetchone()
        return Category(**dict(row)) if row else None

    def create_category(self, category_id: str, name: str, description: str, language: str = 'es') -> None:
        self.connection.execute(
            '''INSERT INTO forum_categories(id, position, name, description, language)
               VALUES (?, (SELECT COALESCE(MAX(position), -1) + 1 FROM forum_categories WHERE language = ?), ?, ?, ?)''',
            (category_id, language, name, description, language),
        )

    def edit_category(self, category_id: str, name: str, description: str) -> None:
        self.connection.execute(
            'UPDATE forum_categories SET name = ?, description = ?, revision = revision + 1 WHERE id = ?',
            (name, description, category_id),
        )

    def delete_category(self, category_id: str, destination: str | None) -> None:
        if destination:
            self.connection.execute('UPDATE forum_topics SET category_id = ? WHERE category_id = ?',
                                    (destination, category_id))
        self.connection.execute('DELETE FROM forum_categories WHERE id = ?', (category_id,))

    def topics(self, viewer: str, *, view: str = "recent", category_id: str = "",
               query: str = "", page: int = 1, language: str = 'es') -> PaginatedMenuPage[Topic]:
        conditions = {"recent": "1", "unread": "unread_count > 0", "saved": "bookmarked = 1",
                      "category": "category_id = :category", "search": f"""(
                          title_search LIKE :query ESCAPE '\\' OR EXISTS (
                              SELECT 1 FROM forum_posts fp WHERE fp.topic_id = topics.id
                              AND fp.hidden = 0 AND {_visible('fp.author_uuid')}
                              AND fp.body_search LIKE :query ESCAPE '\\'
                          ))"""}
        if view == "private":
            where = "is_private = 1"
        elif view == "saved":
            # Saved is the viewer's personal collection. _admitted() still
            # requires current membership for every private discussion.
            where = f"({conditions[view]}) AND (is_private = 1 OR category_id IN (SELECT id FROM forum_categories WHERE language = :language))"
        else:
            where = f"is_private = 0 AND ({conditions[view]}) AND category_id IN (SELECT id FROM forum_categories WHERE language = :language)"
        # User text is always data; escape LIKE wildcard semantics as well.
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        params = {"viewer": viewer, "category": category_id, "query": f"%{escaped}%", "language": language}
        base = f"WITH topics AS ({self._topics_sql()}) SELECT * FROM topics WHERE {where}"
        total = self.connection.execute(f"SELECT COUNT(*) FROM ({base})", params).fetchone()[0]
        safe_page = clamp_page(page, total, TOPICS_PER_PAGE)
        rows = self.connection.execute(
            base + " ORDER BY pinned DESC, last_activity DESC, id DESC LIMIT :limit OFFSET :offset",
            {**params, "limit": TOPICS_PER_PAGE, "offset": (safe_page - 1) * TOPICS_PER_PAGE},
        ).fetchall()
        return PaginatedMenuPage([self._topic(row) for row in rows], total, safe_page, TOPICS_PER_PAGE)

    def topic(self, viewer: str, topic_id: int) -> Topic | None:
        row = self.connection.execute(
            f"SELECT * FROM ({self._topics_sql()}) WHERE id = :topic_id",
            {"viewer": viewer, "topic_id": topic_id},
        ).fetchone()
        return self._topic(row) if row else None

    def post(self, viewer: str, post_id: int) -> Post | None:
        row = self.connection.execute(
            f"""SELECT p.* FROM forum_posts p JOIN forum_topics t ON t.id = p.topic_id
                WHERE p.id = :post_id AND {_visible('p.author_uuid')} AND {_admitted()}""",
            {"viewer": viewer, "post_id": post_id},
        ).fetchone()
        return self._post(row) if row else None

    def posts(self, viewer: str, topic_id: int, page: int = 1) -> PaginatedMenuPage[Post]:
        params = {"viewer": viewer, "topic_id": topic_id}
        base = f"""SELECT p.* FROM forum_posts p JOIN forum_topics t ON t.id = p.topic_id
                   WHERE p.topic_id = :topic_id AND {_visible('p.author_uuid')} AND {_admitted()}"""
        total = self.connection.execute(f"SELECT COUNT(*) FROM ({base})", params).fetchone()[0]
        safe_page = clamp_page(page, total, POSTS_PER_PAGE)
        rows = self.connection.execute(
            base + " ORDER BY p.id LIMIT :limit OFFSET :offset",
            {**params, "limit": POSTS_PER_PAGE, "offset": (safe_page - 1) * POSTS_PER_PAGE},
        ).fetchall()
        return PaginatedMenuPage([self._post(row) for row in rows], total, safe_page, POSTS_PER_PAGE)

    def resume_post(self, viewer: str, topic_id: int) -> int:
        row = self.connection.execute(
            f"""SELECT MIN(p.id) FROM forum_posts p JOIN forum_topics t ON t.id = p.topic_id
                LEFT JOIN forum_read_positions r ON r.topic_id = p.topic_id AND r.user_uuid = :viewer
                WHERE p.topic_id = :topic AND p.id > COALESCE(r.last_post_id, 0)
                AND {_visible('p.author_uuid')} AND {_admitted()}""", {"viewer": viewer, "topic": topic_id},
        ).fetchone()
        return int(row[0] or 0)

    def post_page(self, viewer: str, topic_id: int, post_id: int) -> int:
        count = self.connection.execute(
            f"""SELECT COUNT(*) FROM forum_posts p JOIN forum_topics t ON t.id = p.topic_id
                WHERE p.topic_id = :topic AND p.id < :post AND {_visible('p.author_uuid')} AND {_admitted()}""",
            {"viewer": viewer, "topic": topic_id, "post": post_id},
        ).fetchone()[0]
        return count // POSTS_PER_PAGE + 1

    def mark_read(self, viewer: str, post: Post) -> None:
        self.connection.execute(
            """INSERT INTO forum_read_positions(user_uuid, topic_id, last_post_id) VALUES (?, ?, ?)
                ON CONFLICT(user_uuid, topic_id) DO UPDATE
                SET last_post_id = MAX(last_post_id, excluded.last_post_id)""",
            (viewer, post.topic_id, post.id),
        )

    def write_count(self, author: str, since: int) -> int:
        return self.connection.execute(
            "SELECT COUNT(*) FROM forum_posts WHERE author_uuid = ? AND created_at >= ?",
            (author, since),
        ).fetchone()[0]

    def last_body(self, author: str, since: int) -> str | None:
        row = self.connection.execute(
            """SELECT body_search FROM forum_posts WHERE author_uuid = ? AND created_at >= ?
                ORDER BY id DESC LIMIT 1""", (author, since),
        ).fetchone()
        return row[0] if row else None

    def create_topic(self, author, category_id: str, title: str, body: str, now: int) -> tuple[int, int]:
        cursor = self.connection.execute(
            """INSERT INTO forum_topics(category_id, author_uuid, author_name, title, title_search, created_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
            (category_id, author.uuid, author.username, title, search_key(title), now),
        )
        topic_id = cursor.lastrowid
        return topic_id, self.create_post(author, topic_id, body, now)

    def create_post(self, author, topic_id: int, body: str, now: int) -> int:
        cursor = self.connection.execute(
            """INSERT INTO forum_posts(topic_id, author_uuid, author_name, body, body_search, created_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
            (topic_id, author.uuid, author.username, body, search_key(body), now),
        )
        return cursor.lastrowid

    def edit_post(self, post_id: int, body: str, now: int) -> None:
        self.connection.execute(
            "UPDATE forum_posts SET body = ?, body_search = ?, edited_at = ?, revision = revision + 1 WHERE id = ?",
            (body, search_key(body), now, post_id),
        )

    def bookmark(self, viewer: str, topic_id: int, saved: bool) -> None:
        if saved:
            self.connection.execute("INSERT OR IGNORE INTO forum_bookmarks VALUES (?, ?)", (viewer, topic_id))
        else:
            self.connection.execute("DELETE FROM forum_bookmarks WHERE user_uuid = ? AND topic_id = ?", (viewer, topic_id))

    def moderate(self, actor: str, topic_id: int, action: str, enabled: bool, now: int, post_id: int = 0) -> None:
        if action in {"closed", "pinned"}:
            result = self.connection.execute(
                f"UPDATE forum_topics SET {action} = ? WHERE id = ? AND {action} != ?",
                (int(enabled), topic_id, int(enabled)),
            )
        elif action == "hidden":
            result = self.connection.execute(
                "UPDATE forum_posts SET hidden = ?, revision = revision + 1 WHERE id = ? AND topic_id = ? AND hidden != ?",
                (int(enabled), post_id, topic_id, int(enabled)),
            )
        else:
            raise ValueError("Unsupported forum moderation action")
        if result.rowcount:
            self.connection.execute(
                """INSERT INTO forum_moderation_events(topic_id, post_id, actor_uuid, action, enabled, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)""", (topic_id, post_id or None, actor, action, int(enabled), now),
            )
