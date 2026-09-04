import type { Metadata } from 'next';
import { Bricolage_Grotesque, IBM_Plex_Mono } from 'next/font/google';
import './globals.css';

const bodyFont = Bricolage_Grotesque({
  variable: '--font-sans',
  subsets: ['latin'],
});

const headingFont = Bricolage_Grotesque({
  variable: '--font-heading',
  subsets: ['latin'],
  weight: ['600', '700', '800'],
});

const monoFont = IBM_Plex_Mono({
  variable: '--font-mono',
  subsets: ['latin'],
  weight: ['400', '500', '600'],
});

export const metadata: Metadata = {
  title: 'Coffee Prices | Milwaukee & Twin Cities',
  description: 'Direct-menu coffee and food prices from shops across Milwaukee and the Twin Cities.',
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${bodyFont.variable} ${headingFont.variable} ${monoFont.variable} antialiased`}
      >
        {children}
      </body>
    </html>
  );
}
