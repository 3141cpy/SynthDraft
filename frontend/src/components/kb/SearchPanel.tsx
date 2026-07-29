"use client";

import { useCallback, useState } from "react";
import { ChevronDown, Loader2, Search, X } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { CATEGORY_OPTIONS } from "@/lib/constants";

/** 向后兼容：调用方仍可从本模块导入 CATEGORY_OPTIONS。 */
export { CATEGORY_OPTIONS };

export const TOP_K_OPTIONS = [1, 3, 5, 10, 20] as const;

interface SearchPanelProps {
  query: string;
  topK: number;
  standardFilter: string[];
  categoryFilter: string[];
  standardsOptions: string[];
  loading: boolean;
  onQueryChange: (v: string) => void;
  onTopKChange: (v: number) => void;
  onStandardFilterChange: (v: string[]) => void;
  onCategoryFilterChange: (v: string[]) => void;
  onSearch: () => void;
  onClear: () => void;
}

export function SearchPanel({
  query,
  topK,
  standardFilter,
  categoryFilter,
  standardsOptions,
  loading,
  onQueryChange,
  onTopKChange,
  onStandardFilterChange,
  onCategoryFilterChange,
  onSearch,
  onClear,
}: SearchPanelProps) {
  const canSearch = query.trim().length > 0 && !loading;

  const [standardFilterOpen, setStandardFilterOpen] = useState(false);
  const [categoryFilterOpen, setCategoryFilterOpen] = useState(false);
  const [queryTouched, setQueryTouched] = useState(false);
  const [queryError, setQueryError] = useState(false);

  const handleQueryBlur = useCallback(() => {
    setQueryTouched(true);
    setQueryError(query.trim().length < 1);
  }, [query]);

  const handleQueryChange = useCallback(
    (v: string) => {
      onQueryChange(v);
      if (queryTouched) {
        setQueryError(v.trim().length < 1);
      }
    },
    [onQueryChange, queryTouched],
  );

  const toggleStandard = useCallback(
    (id: string) => {
      if (standardFilter.includes(id)) {
        onStandardFilterChange(standardFilter.filter((v) => v !== id));
      } else {
        onStandardFilterChange([...standardFilter, id]);
      }
    },
    [standardFilter, onStandardFilterChange],
  );

  const toggleCategory = useCallback(
    (id: string) => {
      if (categoryFilter.includes(id)) {
        onCategoryFilterChange(categoryFilter.filter((v) => v !== id));
      } else {
        onCategoryFilterChange([...categoryFilter, id]);
      }
    },
    [categoryFilter, onCategoryFilterChange],
  );

  const standardLabel =
    standardFilter.length === 0
      ? "全部规范"
      : standardFilter.length <= 2
        ? standardFilter.join(", ")
        : `已选 ${standardFilter.length} 项`;

  const categoryLabel =
    categoryFilter.length === 0
      ? "全部分类"
      : categoryFilter.length <= 2
        ? categoryFilter
            .map(
              (c) =>
                CATEGORY_OPTIONS.find((o) => o.value === c)?.label ?? c,
            )
            .join(", ")
        : `已选 ${categoryFilter.length} 项`;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">条款检索</CardTitle>
        <CardDescription>
          输入查询文本，从知识库中检索匹配的国标条款。支持按规范与分类过滤。
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          <Label htmlFor="kb-query">查询文本</Label>
          <Input
            id="kb-query"
            placeholder="例如：圆度公差标注要求"
            value={query}
            onChange={(e) => handleQueryChange(e.target.value)}
            onBlur={handleQueryBlur}
            onKeyDown={(e) => {
              if (e.key === "Enter" && canSearch) {
                e.preventDefault();
                onSearch();
              }
            }}
            disabled={loading}
            aria-invalid={queryError}
            aria-describedby={queryError ? "kb-query-error" : undefined}
          />
          {queryError && (
            <span
              id="kb-query-error"
              className="text-xs text-destructive"
              role="alert"
            >
              请输入查询文本
            </span>
          )}
        </div>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <div className="flex flex-col gap-2">
            <Label htmlFor="kb-top-k">返回数量 (top_k)</Label>
            <Select
              value={String(topK)}
              onValueChange={(v) => onTopKChange(Number(v))}
              disabled={loading}
            >
              <SelectTrigger id="kb-top-k" aria-label="返回数量 (top_k)">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {TOP_K_OPTIONS.map((k) => (
                  <SelectItem key={k} value={String(k)}>
                    {k}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor="kb-standard-filter">规范过滤</Label>
            <DropdownMenu
              open={standardFilterOpen}
              onOpenChange={setStandardFilterOpen}
            >
              <DropdownMenuTrigger asChild>
                <Button
                  id="kb-standard-filter"
                  variant="outline"
                  className="justify-between font-normal"
                  disabled={loading || standardsOptions.length === 0}
                  aria-haspopup="listbox"
                  aria-expanded={standardFilterOpen}
                >
                  <span className="truncate">{standardLabel}</span>
                  <ChevronDown className="h-4 w-4 opacity-50" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent className="max-h-64 w-[--radix-dropdown-menu-trigger-width] min-w-[16rem]">
                {standardsOptions.length === 0 ? (
                  <div className="px-2 py-1.5 text-sm text-muted-foreground">
                    暂无已索引规范
                  </div>
                ) : (
                  standardsOptions.map((s) => (
                    <DropdownMenuCheckboxItem
                      key={s}
                      checked={standardFilter.includes(s)}
                      onCheckedChange={() => toggleStandard(s)}
                      onSelect={(e) => e.preventDefault()}
                    >
                      {s}
                    </DropdownMenuCheckboxItem>
                  ))
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor="kb-category-filter">分类过滤</Label>
            <DropdownMenu
              open={categoryFilterOpen}
              onOpenChange={setCategoryFilterOpen}
            >
              <DropdownMenuTrigger asChild>
                <Button
                  id="kb-category-filter"
                  variant="outline"
                  className="justify-between font-normal"
                  disabled={loading}
                  aria-haspopup="listbox"
                  aria-expanded={categoryFilterOpen}
                >
                  <span className="truncate">{categoryLabel}</span>
                  <ChevronDown className="h-4 w-4 opacity-50" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent className="max-h-64 w-[--radix-dropdown-menu-trigger-width] min-w-[16rem]">
                {CATEGORY_OPTIONS.map((c) => (
                  <DropdownMenuCheckboxItem
                    key={c.value}
                    checked={categoryFilter.includes(c.value)}
                    onCheckedChange={() => toggleCategory(c.value)}
                    onSelect={(e) => e.preventDefault()}
                  >
                    {c.label}
                  </DropdownMenuCheckboxItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>

        <div className="flex items-center justify-end gap-2">
          <Button
            variant="outline"
            onClick={onClear}
            disabled={loading}
          >
            <X className="h-4 w-4" />
            清空
          </Button>
          <Button onClick={onSearch} disabled={!canSearch}>
            {loading ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                检索中...
              </>
            ) : (
              <>
                <Search className="h-4 w-4" />
                检索
              </>
            )}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

/** 内部小工具：根据分类 value 取中文 label。供结果组件复用。 */
export function categoryLabel(value: string): string {
  return CATEGORY_OPTIONS.find((o) => o.value === value)?.label ?? value;
}
