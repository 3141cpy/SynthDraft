"use client";

import { useCallback, useEffect, useState } from "react";
import { BookOpen } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { apiFetch } from "@/lib/api";
import type {
  ClausesQueryResponse,
  StandardsListResponse,
} from "@/lib/types";
import { StandardsList } from "@/components/kb/StandardsList";
import { SearchPanel } from "@/components/kb/SearchPanel";
import { ResultsList } from "@/components/kb/ResultsList";
import { DEFAULT_TOP_K } from "@/lib/constants";

export default function KbPage() {
  const [standards, setStandards] = useState<string[]>([]);
  const [standardsLoading, setStandardsLoading] = useState(false);
  const [standardsError, setStandardsError] = useState<string | null>(null);

  const [query, setQuery] = useState("");
  const [topK, setTopK] = useState<number>(DEFAULT_TOP_K);
  const [standardFilter, setStandardFilter] = useState<string[]>([]);
  const [categoryFilter, setCategoryFilter] = useState<string[]>([]);

  const [results, setResults] = useState<ClausesQueryResponse | null>(null);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [hasSearched, setHasSearched] = useState(false);

  const fetchStandards = useCallback(async () => {
    setStandardsLoading(true);
    setStandardsError(null);
    try {
      const data = await apiFetch<StandardsListResponse>(`/kb/standards`);
      setStandards(data.standards ?? []);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setStandardsError(msg);
      setStandards([]);
    } finally {
      setStandardsLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchStandards();
  }, [fetchStandards]);

  // "/" 键聚焦查询输入（避免在已聚焦 Input/Textarea 时拦截）
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "/") {
        const active = document.activeElement;
        const tag = active?.tagName.toLowerCase();
        const isEditable =
          tag === "input" ||
          tag === "textarea" ||
          (active as HTMLElement | null)?.isContentEditable === true;
        if (!isEditable) {
          e.preventDefault();
          document.getElementById("kb-query")?.focus();
        }
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);

  const handleSearch = useCallback(async () => {
    const q = query.trim();
    if (!q) return;
    setSearchLoading(true);
    setSearchError(null);
    setHasSearched(true);
    try {
      const params = new URLSearchParams();
      params.set("query", q);
      params.set("top_k", String(topK));
      if (standardFilter.length > 0) {
        params.set("standard", standardFilter.join(","));
      }
      if (categoryFilter.length > 0) {
        params.set("category", categoryFilter.join(","));
      }
      const data = await apiFetch<ClausesQueryResponse>(
        `/kb/clauses?${params.toString()}`,
      );
      setResults(data);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setSearchError(msg);
      setResults(null);
    } finally {
      setSearchLoading(false);
    }
  }, [query, topK, standardFilter, categoryFilter]);

  const handleClear = useCallback(() => {
    setQuery("");
    setTopK(DEFAULT_TOP_K);
    setStandardFilter([]);
    setCategoryFilter([]);
    setResults(null);
    setSearchError(null);
    setHasSearched(false);
  }, []);

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6">
      <div className="flex items-center gap-2">
        <BookOpen className="h-6 w-6 text-muted-foreground" />
        <h1 className="text-2xl font-semibold tracking-tight">知识库</h1>
        <Badge variant="outline">GB/T 国标条款</Badge>
      </div>

      <StandardsList
        standards={standards}
        loading={standardsLoading}
        error={standardsError}
        onRetry={fetchStandards}
      />

      <SearchPanel
        query={query}
        topK={topK}
        standardFilter={standardFilter}
        categoryFilter={categoryFilter}
        standardsOptions={standards}
        loading={searchLoading}
        onQueryChange={setQuery}
        onTopKChange={setTopK}
        onStandardFilterChange={setStandardFilter}
        onCategoryFilterChange={setCategoryFilter}
        onSearch={handleSearch}
        onClear={handleClear}
      />

      <ResultsList
        results={results?.results ?? []}
        total={results?.total ?? 0}
        loading={searchLoading}
        error={searchError}
        hasSearched={hasSearched}
        onExampleClick={setQuery}
      />
    </div>
  );
}
