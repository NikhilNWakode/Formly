/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // three.js ships untranspiled ESM examples; let Next handle them.
  transpilePackages: ["three"],
};

export default nextConfig;
