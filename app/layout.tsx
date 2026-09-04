import type { Metadata } from 'next';
import { DM_Sans, Fraunces } from 'next/font/google';
import './globals.css';

const bodyFont = DM_Sans({
  variable: '--font-sans',
  subsets: ['latin'],
});

const headingFont = Fraunces({
  variable: '--font-heading',
  subsets: ['latin'],
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
        className={`${bodyFont.variable} ${headingFont.variable} antialiased`}
      >
        {children}
      </body>
    </html>
  );
}
