"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { isActive, navItems } from "@/components/nav-items";

/**
 * 桌面端侧边栏。`md:` 及以上宽度显示，依据当前 pathname 高亮 active 项。
 */
export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="hidden w-sidebar-width flex-col border-r border-border bg-background md:flex">
      <nav className="flex flex-col gap-1 p-3">
        {navItems.map((item) => {
          const active = isActive(pathname, item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
            >
              <Button
                variant={active ? "secondary" : "ghost"}
                className={cn(
                  "w-full justify-start gap-2 border-l-2 border-transparent",
                  active && "border-primary",
                )}
              >
                <item.icon className="h-4 w-4" />
                {item.label}
              </Button>
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
