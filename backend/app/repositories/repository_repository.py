from sqlalchemy.orm import Session

from app.db.models import Repository


def get_repositories(db: Session) -> list[Repository]:
    return db.query(Repository).order_by(Repository.full_name.asc()).all()


def get_repository_by_id(
    db: Session,
    repository_id: int,
) -> Repository | None:
    return db.query(Repository).filter(Repository.id == repository_id).first()


def get_or_create_repository(
    db: Session,
    full_name: str,
) -> Repository:
    repository = (
        db.query(Repository)
        .filter(Repository.full_name == full_name)
        .one_or_none()
    )

    if repository is not None:
        return repository

    repository = Repository(full_name=full_name)
    db.add(repository)
    db.flush()

    return repository
