"use client";

import { Fragment, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import type { DefectItem, Severity } from "@/lib/types";

const CATEGORY_LABELS: Record<string, string> = {
  title_block: "标题栏",
  layer_naming: "图层命名",
  dimensioning: "尺寸标注",
  tolerance: "形位公差",
  surface_roughness: "表面粗糙度",
  line_type: "线型",
  view_layout: "视图布局",
  text_annotation: "文字标注",
  other: "其他",
};

const SEVERITY_LABELS: Record<Severity, string> = {
  critical: "严重",
  major: "重要",
  minor: "一般",
  warning: "提示",
};

function severityVariant(sev: Severity): "destructive" | "warning" | "secondary" {
  switch (sev) {
    case "critical":
      return "destructive";
    case "major":
      return "warning";
    case "minor":
      return "warning";
    case "warning":
      return "secondary";
    default:
      return "secondary";
  }
}

interface DefectsTableProps {
  defects: DefectItem[];
}

export function DefectsTable({ defects }: DefectsTableProps) {
  const [expanded, setExpanded] = useState<number | null>(null);

  if (defects.length === 0) {
    return (
      <div className="rounded-md border border-dashed p-8 text-center text-sm text-muted-foreground">
        未发现缺陷，图纸符合所选规范要求。
      </div>
    );
  }

  return (
    <div className="rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-10" />
            <TableHead>类别</TableHead>
            <TableHead className="w-20">严重等级</TableHead>
            <TableHead className="w-44">规范引用</TableHead>
            <TableHead className="w-1/4">修改建议</TableHead>
            <TableHead className="w-1/4">证据</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {defects.map((d, i) => {
            const isOpen = expanded === i;
            return (
              <Fragment key={`${i}-${d.standard_clause_id ?? "defect"}`}>
                <TableRow
                  tabIndex={0}
                  role="button"
                  aria-expanded={isOpen}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      setExpanded(isOpen ? null : i);
                    }
                  }}
                  className="cursor-pointer focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
                  onClick={() => setExpanded(isOpen ? null : i)}
                >
                  <TableCell className="w-10">
                    {isOpen ? (
                      <ChevronDown className="h-4 w-4 text-muted-foreground" />
                    ) : (
                      <ChevronRight className="h-4 w-4 text-muted-foreground" />
                    )}
                  </TableCell>
                  <TableCell className="font-medium">
                    {CATEGORY_LABELS[d.category] ?? d.category}
                  </TableCell>
                  <TableCell>
                    <Badge variant={severityVariant(d.severity)} className="font-medium">
                      {SEVERITY_LABELS[d.severity] ?? d.severity}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {d.standard_ref || "-"}
                    {d.standard_clause_id && (
                      <div className="font-mono text-[10px]">
                        {d.standard_clause_id}
                      </div>
                    )}
                  </TableCell>
                  <TableCell className="text-sm">
                    <div className="line-clamp-1">{d.suggestion || "-"}</div>
                  </TableCell>
                  <TableCell className="text-sm">
                    <div className="line-clamp-1">{d.evidence || "-"}</div>
                  </TableCell>
                </TableRow>
                {isOpen && (
                  <TableRow className="bg-muted/30 hover:bg-muted/30">
                    <TableCell colSpan={6} className="space-y-3 align-top">
                      {d.evidence && (
                        <div className="space-y-1">
                          <div className="text-xs font-semibold text-muted-foreground">
                            证据
                          </div>
                          <div className="whitespace-pre-wrap text-sm">
                            {d.evidence}
                          </div>
                        </div>
                      )}
                      {d.suggestion && (
                        <div className="space-y-1">
                          <div className="text-xs font-semibold text-muted-foreground">
                            修改建议
                          </div>
                          <div className="whitespace-pre-wrap text-sm">
                            {d.suggestion}
                          </div>
                        </div>
                      )}
                      {d.coordinate && (
                        <div className="text-xs text-muted-foreground">
                          坐标: ({d.coordinate.x}, {d.coordinate.y})
                        </div>
                      )}
                    </TableCell>
                  </TableRow>
                )}
              </Fragment>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
