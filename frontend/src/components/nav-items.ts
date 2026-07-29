import {
  BookOpen,
  FileSearch,
  Wand2,
  type LucideIcon,
} from "lucide-react";

/** 侧边栏导航项结构。 */
export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
}

/** 主导航项，桌面 sidebar 与移动端 Sheet 共用。 */
export const navItems: NavItem[] = [
  { href: "/review", label: "审图工作台", icon: FileSearch },
  { href: "/generate", label: "生成工作台", icon: Wand2 },
  { href: "/kb", label: "知识库", icon: BookOpen },
];

/** 判断给定 pathname 是否处于指定 href 下（含子路由）。 */
export function isActive(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}
