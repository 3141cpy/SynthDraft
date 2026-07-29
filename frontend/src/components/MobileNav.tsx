"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Menu, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetTitle,
} from "@/components/ui/sheet";
import { cn } from "@/lib/utils";
import { isActive, navItems } from "@/components/nav-items";

/**
 * 移动端导航。`md:` 以下显示汉堡按钮，点击展开 Sheet 抽屉。
 * - Esc 关闭、点击遮罩关闭：由 Radix Dialog 内置支持
 * - 路由切换后自动关闭：useEffect 监听 pathname
 * - 点击导航项关闭：SheetClose 包裹
 */
export function MobileNav() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  // 路由切换后自动关闭抽屉
  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <Button
        variant="ghost"
        size="icon"
        className="h-9 w-9 md:hidden"
        onClick={() => setOpen((v) => !v)}
        aria-label={open ? "关闭菜单" : "打开菜单"}
        aria-expanded={open}
      >
        {open ? (
          <X className="h-4 w-4" />
        ) : (
          <Menu className="h-4 w-4" />
        )}
      </Button>
      <SheetContent
        side="left"
        className="w-sidebar-width max-w-[85vw] p-0"
      >
        <SheetTitle className="sr-only">主导航</SheetTitle>
        <nav className="flex flex-col gap-1 p-3">
          {navItems.map((item) => {
            const active = isActive(pathname, item.href);
            return (
              <SheetClose asChild key={item.href}>
                <Link
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
              </SheetClose>
            );
          })}
        </nav>
      </SheetContent>
    </Sheet>
  );
}
