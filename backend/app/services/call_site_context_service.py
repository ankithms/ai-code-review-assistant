from app.schemas.fix_context import CallSite
from app.services.symbol_context_service import SymbolContextService


class CallSiteContextService:
    def __init__(self, symbol_service: SymbolContextService | None = None) -> None:
        self.symbol_service = symbol_service or SymbolContextService()

    def collect_call_sites(
        self,
        file_contents: dict[str, str],
        enclosing_symbol: str | None,
        target_file: str,
        changed_files: set[str],
        max_call_sites: int = 8,
    ) -> list[CallSite]:
        return self.symbol_service.call_sites(
            file_contents=file_contents,
            symbol_name=enclosing_symbol,
            target_file=target_file,
            changed_files=changed_files,
            max_call_sites=max_call_sites,
        )
