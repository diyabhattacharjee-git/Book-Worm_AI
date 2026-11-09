import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { PageHeader } from '../components/ui'

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <h2 className="text-xl font-semibold">{title}</h2>
      {children}
    </section>
  )
}

function Bullets({ items }: { items: ReactNode[] }) {
  return <ul className="list-disc space-y-1 pl-5">{items.map((item, i) => <li key={i}>{item}</li>)}</ul>
}

export default function Privacy() {
  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader eyebrow="BookWorm" title="Privacy policy">Last updated 9 November 2026</PageHeader>
      <div className="space-y-8 leading-relaxed text-ink-soft">
        <p>This page explains what BookWorm collects, why, who it is shared with, and how you can remove it.</p>

        <Section title="What we collect">
          <Bullets items={[
            'Account details: your email address, username, display name and password (stored only as a secure hash). If you sign in with Google, we also keep your Google account identifier.',
            'Profile details you choose to add: a photo, a bio, your city or area, and a private contact note.',
            'Reading activity: your shelves, ratings, reviews, reading plans, goals, to-do items, preferences, searches, and the books you view, save or dismiss.',
            'Marketplace activity: the listings and photos you post, and messages between buyers and sellers. Location data embedded in photos is removed when they are uploaded.',
            'Assistant conversations: what you ask the reading assistant. These are saved to your account only when you are logged in.',
            'eBay connection, if you choose to connect: an encrypted authorisation token and a record of the listings you publish. We never see your eBay password.',
          ]} />
        </Section>

        <Section title="How we use it">
          <Bullets items={[
            'To run your account and send one-time sign-in and verification codes by email.',
            'To personalise recommendations from your ratings, shelf, saves, dismissals and recent searches. We do not infer sensitive personal attributes from what you read.',
            'To show your listings to buyers, deliver messages, and publish to eBay when you ask us to.',
            'To keep the service safe, including handling reports and moderating content.',
          ]} />
          <p>We do not sell your personal data, show advertising, or use analytics or advertising trackers.</p>
        </Section>

        <Section title="What other people can see">
          <p>Your listings and their photos, your reviews, your display name, and your city if you choose to show it are public. Your email address is never shown to other users.</p>
        </Section>

        <Section title="Services that process data for us">
          <Bullets items={[
            'Vercel hosts the website, and Neon hosts the database.',
            'Cloudinary may store uploaded photos; otherwise they are kept in our database.',
            'Groq processes your assistant messages and recent conversation to write replies.',
            'Google Books and Open Library receive book search terms, without your account details.',
            'eBay receives book searches for price comparisons and, only if you connect your account and publish, the details and photos of that listing.',
            'Our email provider delivers one-time codes. Google handles sign-in if you choose it.',
          ]} />
        </Section>

        <Section title="Cookies">
          <p>We use one essential cookie to keep you logged in. It lasts up to 7 days and cannot be read by scripts on the page. We use no advertising or analytics cookies.</p>
        </Section>

        <Section title="How long we keep it">
          <p>We keep your data until you delete it or close your account. One-time codes expire after 10 minutes. If eBay tells us an eBay member has deleted their account, we remove our saved copies of that member’s eBay listings.</p>
        </Section>

        <Section title="Your choices">
          <p>From <Link to="/settings" className="link">Profile & settings</Link> you can:</p>
          <Bullets items={[
            'Change your profile details, or hide your city and turn off buyer messages.',
            'Reset learned preferences, or delete your reading history and assistant chats.',
            'Sign out of every device.',
            'Delete your account, which permanently removes your listings and photos, reviews, shelves, plans, conversations and messages. Reports you filed are kept without your name.',
          ]} />
          <p>You can disconnect eBay at any time from the eBay tab in your seller dashboard.</p>
        </Section>

        <Section title="Changes to this policy">
          <p>If this policy changes, we will update this page and the date at the top.</p>
        </Section>
      </div>
    </div>
  )
}
