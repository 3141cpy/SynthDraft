import {
  Card,
  CardContent,
  CardHeader,
} from "@/components/ui/card";

/** 模拟一张 Card 的高度（标题 + 描述 + 几行内容）。 */
export function CardSkeleton() {
  return (
    <Card>
      <CardHeader>
        <div className="h-5 w-1/3 animate-pulse rounded bg-muted" />
        <div className="h-4 w-1/2 animate-pulse rounded bg-muted" />
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="h-4 w-full animate-pulse rounded bg-muted" />
        <div className="h-4 w-5/6 animate-pulse rounded bg-muted" />
        <div className="h-4 w-2/3 animate-pulse rounded bg-muted" />
      </CardContent>
    </Card>
  );
}

/** 模拟 5 行表格。 */
export function TableSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="flex flex-col gap-2">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex gap-3">
          <div className="h-4 w-1/4 animate-pulse rounded bg-muted" />
          <div className="h-4 w-1/4 animate-pulse rounded bg-muted" />
          <div className="h-4 w-1/2 animate-pulse rounded bg-muted" />
        </div>
      ))}
    </div>
  );
}

/** 模拟详情页头部（标题 + 三列元信息）。 */
export function DetailSkeleton() {
  return (
    <Card>
      <CardHeader>
        <div className="h-6 w-1/2 animate-pulse rounded bg-muted" />
        <div className="h-4 w-1/3 animate-pulse rounded bg-muted" />
      </CardHeader>
      <CardContent className="grid gap-4 md:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="flex flex-col gap-2">
            <div className="h-3 w-1/3 animate-pulse rounded bg-muted" />
            <div className="h-5 w-2/3 animate-pulse rounded bg-muted" />
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
