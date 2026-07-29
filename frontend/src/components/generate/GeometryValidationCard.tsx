"use client";

import { AlertCircle, CheckCircle2, Box } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import type { GeometryValidation } from "@/lib/types";
import { formatBoundingBox, formatNumber } from "@/lib/format";

interface GeometryValidationCardProps {
  validation: GeometryValidation;
}

export function GeometryValidationCard({
  validation,
}: GeometryValidationCardProps) {
  const valid = validation.is_valid;

  return (
    <div className="flex flex-col gap-3 rounded-lg border p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Box className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-medium">几何校验</span>
          {valid ? (
            <Badge variant="success">
              <CheckCircle2 className="h-3 w-3" />
              有效
            </Badge>
          ) : (
            <Badge variant="destructive">
              <AlertCircle className="h-3 w-3" />
              无效
            </Badge>
          )}
          {validation.backend && (
            <Badge variant="outline" className="text-xs">
              {validation.backend}
            </Badge>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div className="flex flex-col gap-0.5">
          <span className="text-xs text-muted-foreground">体积</span>
          <span className="font-mono text-sm tabular-nums">
            {formatNumber(validation.volume, 3)} mm³
          </span>
        </div>
        <div className="flex flex-col gap-0.5">
          <span className="text-xs text-muted-foreground">表面积</span>
          <span className="font-mono text-sm tabular-nums">
            {formatNumber(validation.surface_area, 3)} mm²
          </span>
        </div>
        <div className="flex flex-col gap-0.5">
          <span className="text-xs text-muted-foreground">包围盒 (DX×DY×DZ)</span>
          <span className="font-mono text-sm tabular-nums">
            {formatBoundingBox(validation.bounding_box)}
          </span>
        </div>
      </div>

      {validation.errors.length > 0 && (
        <>
          <Separator />
          <div className="flex flex-col gap-1">
            <span className="text-xs font-medium text-destructive">
              校验错误（{validation.errors.length} 项）
            </span>
            <ul className="list-disc space-y-0.5 pl-5 text-xs text-destructive">
              {validation.errors.map((e, i) => (
                <li key={i}>{e}</li>
              ))}
            </ul>
          </div>
        </>
      )}
    </div>
  );
}
