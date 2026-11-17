import { API_URL } from "@/lib/api";

type Live = { price: string | null; icon: string | null };

/** Today's US price from the public marketplace; nothing is shown if it can't be read. */
export async function live(slug: string): Promise<Live> {
  try {
    const response = await fetch(`${API_URL}/marketplace/${slug}/`, { next: { revalidate: 3600 } });
    if (!response.ok) return { price: null, icon: null };
    const data = await response.json();
    const us = (data.countries ?? []).find(
      (country: { code: string; offered?: boolean }) => country.code === "US" && country.offered,
    );
    return { price: us?.price ?? null, icon: data.icon_url ?? null };
  } catch {
    return { price: null, icon: null };
  }
}
