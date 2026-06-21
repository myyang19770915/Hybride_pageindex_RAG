from sqlalchemy.orm import Session, selectinload

from app.models import KmDocument, KmDocumentPage, KmIngestionJob


class DocumentRepository:
    """SQLAlchemy persistence boundary for documents and ingestion jobs."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add_document(self, document: KmDocument) -> KmDocument:
        self.session.add(document)
        return document

    def add_job(self, job: KmIngestionJob) -> KmIngestionJob:
        self.session.add(job)
        return job

    def get_document(self, document_id: str) -> KmDocument | None:
        return (
            self.session.query(KmDocument)
            .options(selectinload(KmDocument.pages))
            .filter(KmDocument.document_id == document_id)
            .one_or_none()
        )

    def get_job(self, job_id: str) -> KmIngestionJob | None:
        return self.session.get(KmIngestionJob, job_id)

    def list_documents(self) -> list[KmDocument]:
        return list(self.session.query(KmDocument).order_by(KmDocument.created_at.desc()).all())

    def demote_latest(self, file_name: str, owner: str | None) -> None:
        query = self.session.query(KmDocument).filter(KmDocument.file_name == file_name)
        query = (
            query.filter(KmDocument.owner.is_(None))
            if owner is None
            else query.filter(KmDocument.owner == owner)
        )
        for document in query.all():
            document.is_latest = False

    def replace_pages(self, document_id: str, pages: list[KmDocumentPage]) -> None:
        (
            self.session.query(KmDocumentPage)
            .filter(KmDocumentPage.document_id == document_id)
            .delete()
        )
        self.session.add_all(pages)

    def list_pages(self, document_id: str) -> list[KmDocumentPage]:
        return list(
            self.session.query(KmDocumentPage)
            .filter(KmDocumentPage.document_id == document_id)
            .order_by(KmDocumentPage.page_number.asc())
            .all()
        )

    def delete_document(self, document_id: str) -> None:
        document = self.get_document(document_id)
        if document:
            self.session.delete(document)

    def commit(self) -> None:
        self.session.commit()
