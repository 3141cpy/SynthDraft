/** API 后端地址：可通过环境变量 API_ORIGIN 配置，默认指向本地后端 */
const apiOrigin = process.env.API_ORIGIN || "http://localhost:8000";

/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    return [
      {
        source: '/api/v1/:path*',
        destination: `${apiOrigin}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
