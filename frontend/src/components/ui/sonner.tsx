"use client"

import { useTheme } from "next-themes"
import { Toaster as Sonner, toast } from "sonner"
import {
  AlertTriangle,
  CheckCircle,
  Info,
  XCircle,
} from "lucide-react"

type ToasterProps = React.ComponentProps<typeof Sonner>

/**
 * Toast 语义分级配置：
 * - success：绿色 + CheckCircle 图标，4s 自动消失（沿用全局 duration）
 * - error：红色 + XCircle 图标，需手动关闭（调用方传 duration: Infinity，
 *   或使用下方 re-export 的 toast.error 默认持久化）
 * - warning：黄色 + AlertTriangle 图标，5s 自动消失
 * - info：蓝色 + Info 图标，4s 自动消失
 *
 * 注：sonner 的 toastOptions.duration 为全局默认，不支持按 type 设置。
 * 因此 success/info 使用全局 4000ms，warning/error 通过下方封装的 toast
 * 方法注入对应 duration（warning 5000，error Infinity）。
 */
const SUCCESS_DURATION = 4000
const WARNING_DURATION = 5000
const INFO_DURATION = 4000
const ERROR_DURATION = Number.POSITIVE_INFINITY

/** 为 error/warning 注入默认 duration 的 toast 封装。 */
const configuredToast = Object.assign(
  (message: Parameters<typeof toast>[0], data?: Parameters<typeof toast>[1]) =>
    toast(message, data),
  {
    success: (
      message: Parameters<typeof toast.success>[0],
      data?: Parameters<typeof toast.success>[1],
    ) =>
      toast.success(message, {
        duration: SUCCESS_DURATION,
        ...data,
      }),
    info: (
      message: Parameters<typeof toast.info>[0],
      data?: Parameters<typeof toast.info>[1],
    ) =>
      toast.info(message, {
        duration: INFO_DURATION,
        ...data,
      }),
    warning: (
      message: Parameters<typeof toast.warning>[0],
      data?: Parameters<typeof toast.warning>[1],
    ) =>
      toast.warning(message, {
        duration: WARNING_DURATION,
        ...data,
      }),
    error: (
      message: Parameters<typeof toast.error>[0],
      data?: Parameters<typeof toast.error>[1],
    ) =>
      toast.error(message, {
        duration: ERROR_DURATION,
        ...data,
      }),
    custom: toast.custom,
    message: toast.message,
    promise: toast.promise,
    dismiss: toast.dismiss,
    loading: toast.loading,
    getHistory: toast.getHistory,
    getToasts: toast.getToasts,
  },
)

const Toaster = ({ ...props }: ToasterProps) => {
  const { theme = "system" } = useTheme()

  return (
    <Sonner
      theme={theme as ToasterProps["theme"]}
      className="toaster group"
      closeButton
      duration={SUCCESS_DURATION}
      icons={{
        success: <CheckCircle className="h-5 w-5 text-success" />,
        error: <XCircle className="h-5 w-5 text-destructive" />,
        warning: (
          <AlertTriangle className="h-5 w-5 text-warning" />
        ),
        info: <Info className="h-5 w-5 text-info" />,
      }}
      toastOptions={{
        classNames: {
          toast:
            "group toast group-[.toaster]:bg-background group-[.toaster]:text-foreground group-[.toaster]:border-border group-[.toaster]:shadow-lg",
          description: "group-[.toast]:text-muted-foreground",
          actionButton:
            "group-[.toast]:bg-primary group-[.toast]:text-primary-foreground",
          cancelButton:
            "group-[.toast]:bg-muted group-[.toast]:text-muted-foreground",
          success:
            "!border-success/40 !bg-success/10 [&_[data-icon]]:text-success",
          error:
            "!border-destructive/40 !bg-destructive/10 [&_[data-icon]]:text-destructive",
          warning:
            "!border-warning/40 !bg-warning/10 [&_[data-icon]]:text-warning",
          info: "!border-info/40 !bg-info/10 [&_[data-icon]]:text-info",
        },
      }}
      {...props}
    />
  )
}

export { Toaster, configuredToast as toast }
