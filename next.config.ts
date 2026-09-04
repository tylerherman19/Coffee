import type { NextConfig } from 'next';

const onGitHubPages = process.env.GITHUB_ACTIONS === 'true';
const nextConfig: NextConfig = {
  output: onGitHubPages ? 'export' : undefined,
  basePath: onGitHubPages ? '/Coffee' : '',
  assetPrefix: onGitHubPages ? '/Coffee/' : '',
};

export default nextConfig;
