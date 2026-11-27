from __future__ import annotations

from typing import Any, Dict, Optional

from ..cache import BaseCache
from ..clients.amint import AMintClient, AMintError, TransformOptions
from ..clients.analysis import AnalysisClient, AnalysisError, AnalysisJobOptions
from ..config import get_settings
from ..logging import get_logger

logger = get_logger(__name__)
ANALYSIS_FAILURE_EVENT = "pricing.workflow.analysis.failed"


class PricingWorkflow:
    def __init__(
        self,
        amint_client: AMintClient,
        analysis_client: AnalysisClient,
        cache: BaseCache,
    ) -> None:
        settings = get_settings()
        self._amint = amint_client
        self._analysis = analysis_client
        self._cache = cache
        self._cache_ttl = settings.cache_ttl_seconds
        self._amint_model = settings.amint_llm_model
        self._amint_better_model = settings.amint_llm_better_model
        self._amint_llm_base_url = settings.amint_llm_base_url

    def _transform_options(self, url: str) -> TransformOptions:
        return TransformOptions(
            url=url,
            model=self._amint_model,
            better_model=self._amint_better_model,
            base_url_override=self._amint_llm_base_url,
        )

    def _pricing_cache_key(self, url: str) -> str:
        # The LLM configuration is part of the key, so changing the model or the
        # endpoint never serves YAML extracted with the previous configuration.
        return "|".join(
            (
                f"pricing:{url}",
                self._amint_model,
                self._amint_better_model,
                self._amint_llm_base_url,
            )
        )

    async def ensure_pricing_yaml(self, url: str, refresh: bool = False) -> str:
        cache_key = self._pricing_cache_key(url)
        if not refresh:
            cached = await self._cache.get(cache_key)
            if cached:
                logger.info("pricing.workflow.cache.hit", url=url)
                return cached

        logger.info("pricing.workflow.cache.miss", url=url, refresh=refresh)
        try:
            yaml_content = await self._amint.transform(self._transform_options(url))
        except AMintError as exc:  # pragma: no cover - network dependent
            logger.error("pricing.workflow.transform.failed", url=url, error=str(exc))
            raise

        await self._cache.set(cache_key, yaml_content, ttl_seconds=self._cache_ttl)
        return yaml_content

    async def run_optimal(
        self,
        url: str,
        filters: Optional[Dict[str, Any]] = None,
        solver: str = "minizinc",
        objective: str = "minimize",
        refresh: bool = False,
        yaml_content: Optional[str] = None,
    ) -> Dict[str, Any]:
        if yaml_content is None:
            yaml_content = await self.ensure_pricing_yaml(url, refresh=refresh)
        try:
            result = await self._analysis.submit_job(
                AnalysisJobOptions(
                    yaml_content=yaml_content,
                    operation="optimal",
                    solver=solver,
                    filters=filters,
                    objective=objective,
                )
            )
        except AnalysisError as exc:  # pragma: no cover - network dependent
            logger.error(ANALYSIS_FAILURE_EVENT, url=url, error=str(exc))
            raise
        return {
            "request": {
                "url": url,
                "filters": filters,
                "solver": solver,
                "objective": objective,
            },
            "result": result,
        }

    async def run_subscriptions(
        self,
        url: str,
        filters: Optional[Dict[str, Any]] = None,
        solver: str = "minizinc",
        refresh: bool = False,
        yaml_content: Optional[str] = None,
    ) -> Dict[str, Any]:
        if yaml_content is None:
            yaml_content = await self.ensure_pricing_yaml(url, refresh=refresh)
        try:
            operation = "filter" if filters else "subscriptions"
            result = await self._analysis.submit_job(
                AnalysisJobOptions(
                    yaml_content=yaml_content,
                    operation=operation,
                    solver=solver,
                    filters=filters,
                )
            )
        except AnalysisError as exc:  # pragma: no cover - network dependent
            logger.error(ANALYSIS_FAILURE_EVENT, url=url, error=str(exc))
            raise
        return {
            "request": {
                "url": url,
                "filters": filters,
                "solver": solver,
            },
            "result": result,
        }

    async def run_validation(
        self,
        url: Optional[str] = None,
        solver: str = "minizinc",
        refresh: bool = False,
        yaml_content: Optional[str] = None,
    ) -> Dict[str, Any]:
        if solver not in {"minizinc", "choco"}:
            raise ValueError("solver must be either 'minizinc' or 'choco'.")

        if yaml_content is None:
            if not url:
                raise ValueError("Either yaml_content or url is required for validation")
            yaml_content = await self.ensure_pricing_yaml(url, refresh=refresh)

        try:
            result = await self._analysis.submit_job(
                AnalysisJobOptions(
                    yaml_content=yaml_content,
                    operation="validate",
                    solver=solver,
                )
            )
        except AnalysisError as exc:  # pragma: no cover - network dependent
            logger.error(ANALYSIS_FAILURE_EVENT, url=url, error=str(exc))
            raise

        return {
            "request": {
                "url": url,
                "solver": solver,
                "refresh": refresh,
            },
            "result": result,
        }

    async def run_summary(
        self,
        url: Optional[str] = None,
        yaml_content: Optional[str] = None,
        refresh: bool = False,
    ) -> Dict[str, Any]:
        if yaml_content is None:
            if not url:
                raise ValueError("Either yaml_content or url is required for summary")
            yaml_content = await self.ensure_pricing_yaml(url, refresh=refresh)

        summary = await self._analysis.get_summary(yaml_content)
        return {
            "request": {
                "url": url,
                "refresh": refresh,
            },
            "summary": summary,
        }

    async def get_ipricing(
        self,
        url: Optional[str] = None,
        yaml_content: Optional[str] = None,
        refresh: bool = False,
    ) -> Dict[str, Any]:
        if yaml_content is None:
            if not url:
                raise ValueError("Either yaml_content or url is required to retrieve the iPricing document")
            yaml_content = await self.ensure_pricing_yaml(url, refresh=refresh)
            source = "amint"
        else:
            source = "upload"

        return {
            "request": {
                "url": url,
                "refresh": refresh,
            },
            "pricing_yaml": yaml_content,
            "source": source,
        }
