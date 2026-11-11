"""Authorized subforum management, independent of client presentation."""

from uuid import uuid4

from .models import (
    ForumError, MAX_CATEGORIES, MAX_CATEGORY_NAME_LENGTH, MAX_CATEGORY_DESCRIPTION_LENGTH,
)
from .text import search_key, validate_text


def validate_category_text(value: object, *, description: bool = False) -> str:
    limit = MAX_CATEGORY_DESCRIPTION_LENGTH if description else MAX_CATEGORY_NAME_LENGTH
    if not isinstance(value, str) or len(value) > limit:
        raise ForumError('forum-error-category-description' if description else 'forum-error-category-name', limit=limit)
    if description and not value.strip():
        return ''
    if not description and not value.strip():
        raise ForumError('forum-error-category-name', limit=limit)
    return validate_text(value, title=not description)


class CategoryService:
    def __init__(self, forum):
        self.forum = forum
        self.repository = forum.repository

    def authorize(self, viewer: str, *, writing: bool = False) -> None:
        if not self.forum.is_moderator(viewer):
            raise ForumError('forum-error-category-admin')
        self.forum.account(viewer, writing=writing)

    def get(self, viewer: str, category_id: str):
        self.authorize(viewer)
        category = self.repository.category(category_id)
        if category is None:
            raise ForumError('forum-error-missing')
        return category

    def _validate(self, viewer: str, name: str, description: str, category_id: str = '') -> tuple[str, str]:
        name = validate_category_text(name)
        description = validate_category_text(description, description=True)
        if any(category.id != category_id and category.name and search_key(category.name) == search_key(name)
               for category in self.repository.categories(viewer)):
            raise ForumError('forum-error-category-duplicate')
        return name, description

    @staticmethod
    def _revision(category, revision: int) -> None:
        if type(revision) is not int or revision != category.revision:
            raise ForumError('forum-error-category-conflict')

    def create(self, viewer: str, name: str, description: str = '') -> str:
        with self.repository.atomic():
            self.authorize(viewer, writing=True)
            if len(self.repository.categories(viewer)) >= MAX_CATEGORIES:
                raise ForumError('forum-error-category-limit', limit=MAX_CATEGORIES)
            name, description = self._validate(viewer, name, description)
            category_id = str(uuid4())
            self.repository.create_category(category_id, name, description)
            return category_id

    def edit(self, viewer: str, category_id: str, name: str, description: str, revision: int) -> None:
        with self.repository.atomic():
            self.authorize(viewer, writing=True)
            category = self.get(viewer, category_id)
            self._revision(category, revision)
            name, description = self._validate(viewer, name, description, category_id)
            self.repository.edit_category(category_id, name, description)

    def delete(self, viewer: str, category_id: str, revision: int, *, destination: str | None = None) -> None:
        with self.repository.atomic():
            self.authorize(viewer, writing=True)
            category = self.get(viewer, category_id)
            self._revision(category, revision)
            if destination is not None:
                if destination == category_id:
                    raise ForumError('forum-error-category-destination')
                self.get(viewer, destination)
            elif category.topic_count:
                raise ForumError('forum-error-category-destination')
            self.repository.delete_category(category_id, destination)
