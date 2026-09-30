/** Shapes returned by the VerifyGH API. Money is always a string: it is a
 *  Decimal on the server, and putting it through a JS number would be the
 *  fastest way to lose a pesewa. */

export type Role = "USER" | "SUPPORT" | "ADMIN" | "SUPER_ADMIN";

export type User = {
  id: string;
  email: string;
  full_name: string;
  phone: string;
  phone_display: string;
  role: Role;
  is_email_verified: boolean;
  is_phone_verified: boolean;
  is_suspended: boolean;
  is_two_factor_enabled: boolean;
  has_accepted_current_terms: boolean;
  accepted_terms_version: string;
  admin_permissions: string[];
  created_at: string;
};

export type Wallet = {
  id: string;
  currency: string;
  /** Cash the user paid in. Withdrawable, refundable as cash. */
  balance: string;
  /** Promotional credit (referral bonuses). Spendable, never withdrawable. */
  promo_balance: string;
  /** promo_balance + balance: what a purchase can actually draw on. */
  spendable: string;
  is_frozen: boolean;
  total_deposited: string;
  total_spent: string;
  promo_granted: string;
  updated_at: string;
};

export type WalletSummary = {
  wallet: Wallet;
  today_spending: string;
  active_orders: number;
  successful_orders: number;
  total_orders: number;
};

export type LedgerEntryType =
  | "DEPOSIT"
  | "PURCHASE"
  | "REFUND"
  | "ADJUSTMENT"
  | "WITHDRAWAL"
  | "REVERSAL"
  | "REFERRAL_BONUS";

/** Which bucket of the wallet a ledger entry moved. */
export type FundType = "CASH" | "PROMO";

export type Transaction = {
  id: string;
  reference: string;
  entry_type: LedgerEntryType;
  funds: FundType;
  direction: "CREDIT" | "DEBIT";
  status: string;
  amount: string;
  signed_amount: string;
  currency: string;
  balance_after: string;
  description: string;
  related_order_id: string | null;
  related_payment_id: string | null;
  created_at: string;
};

/**
 * `OTP_REQUIRED` and `PHONE_AUTH` are opposites and must never be merged.
 *
 * OTP_REQUIRED - the provider texted a code and is waiting for us to submit
 * it. The customer has something to type into VerifyGH.
 *
 * PHONE_AUTH - the handset has been prompted. The customer has nothing to type
 * here, and must never be asked for their Mobile Money PIN by us.
 */
export type PaymentStatus =
  | "PENDING"
  | "PROCESSING"
  | "OTP_REQUIRED"
  | "PHONE_AUTH"
  | "SUCCESS"
  | "FAILED"
  | "CANCELLED"
  | "EXPIRED";

export type Payment = {
  id: string;
  reference: string;
  amount: string;
  currency: string;
  status: PaymentStatus;
  network: string;
  network_label: string;
  phone_display: string;
  instructions: string;
  failure_reason: string;
  expires_at: string | null;
  completed_at: string | null;
  created_at: string;
};

export type MomoNetwork = {
  value: string;
  label: string;
  prefixes: string[];
};

export type PaymentOptions = {
  networks: MomoNetwork[];
  currency: string;
  min_deposit: string;
  max_deposit: string;
  max_balance: string;
  quick_amounts: string[];
  /** False while there is nothing to buy; the deposit endpoint would refuse. */
  deposits_enabled: boolean;
  /** Shown to the user when deposits_enabled is false. Empty otherwise. */
  deposits_disabled_reason: string;
};

export type CountryOption = {
  code: string;
  name: string;
  flag_emoji: string;
  dial_code: string;
  price: string;
  currency: string;
  available: boolean;
  available_count: number | null;
  supports_sms: boolean;
  supports_voice: boolean;
  ttl_minutes: number;
};

export type ServiceCategory =
  | "SOCIAL"
  | "MESSAGING"
  | "EMAIL"
  | "DEVELOPER"
  | "BUSINESS"
  | "FINANCE"
  | "OTHER";

export type Service = {
  slug: string;
  name: string;
  category: ServiceCategory;
  icon_url: string;
  accent_color: string;
  description: string;
  supports_sms: boolean;
  supports_voice: boolean;
  is_maintenance: boolean;
  maintenance_note: string;
  available: boolean;
  from_price: string | null;
  currency: string;
  /** How many countries offer this service. Always present. */
  country_count: number;
  /**
   * Only on the detail endpoint, `/services/<slug>/`.
   *
   * The list deliberately omits it: across the full provider catalogue it is
   * about 15,000 entries, and shipping them all made the marketplace a 3.4MB
   * download on every visit.
   */
  countries?: CountryOption[];
};

/** A service fetched from `/services/<slug>/`, where countries are guaranteed. */
export type ServiceDetail = Service & { countries: CountryOption[] };

export type MarketplaceResponse = {
  results: Service[];
  categories: { value: string; label: string }[];
  countries: { code: string; name: string; dial_code: string; flag_emoji: string }[];
  count: number;
};

export type OrderStatus =
  | "CREATED"
  | "PAYMENT_PENDING"
  | "PROCESSING"
  | "NUMBER_ASSIGNED"
  | "WAITING_FOR_CODE"
  | "CODE_RECEIVED"
  | "COMPLETED"
  | "EXPIRED"
  | "CANCELLED"
  | "FAILED"
  | "REFUNDED";

export type OrderEvent = {
  id: string;
  status: OrderStatus;
  label: string;
  detail: string;
  created_at: string;
};

export type OrderSummary = {
  id: string;
  reference: string;
  service_name: string;
  service_slug: string;
  service_icon: string;
  country_name: string;
  country_code: string;
  country_flag: string;
  country_dial_code: string;
  phone_number: string;
  price: string;
  currency: string;
  status: OrderStatus;
  refund_status: "NONE" | "PENDING" | "COMPLETED" | "REJECTED";
  expires_at: string | null;
  created_at: string;
};

export type Order = OrderSummary & {
  failure_reason: string;
  verification_code: string;
  verification_message: string;
  code_display_allowed: boolean;
  code_received_at: string | null;
  completed_at: string | null;
  seconds_remaining: number;
  can_cancel: boolean;
  can_complete: boolean;
  /** Whether "Report a problem" is offered: a code arrived, within the window, no case yet. */
  can_report: boolean;
  report_window_ends_at: string | null;
  issue: OrderIssue | null;
  /** Set on a free replacement: the reference of the order it replaces. */
  replacement_for: string | null;
  /** Until when the provider lets this number receive another code. */
  reusable_until: string | null;
  /** Whether "Use this number again" is offered right now. */
  can_reuse: boolean;
  /** What reusing would cost now; null unless can_reuse. */
  reuse_price: string | null;
  /** Set on a reuse: the reference of the order whose number it reused. */
  reuse_of: string | null;
  events: OrderEvent[];
  refund: {
    reference: string;
    amount: string;
    currency: string;
    reason: string;
    status: string;
    completed_at: string | null;
  } | null;
};

export type OrderLiveStatus = {
  reference: string;
  status: OrderStatus;
  phone_number: string;
  verification_code: string;
  code_display_allowed: boolean;
  seconds_remaining: number;
  refund_status: string;
  failure_reason: string;
  poll_interval_seconds: number;
};

export type Quote = {
  service: string;
  service_name: string;
  country: string;
  country_name: string;
  price: string;
  currency: string;
  supports_sms: boolean;
  supports_voice: boolean;
  ttl_minutes: number;
  availability: Availability;
  available_count: number | null;
  offering_id: string;
  wallet_balance: string;
  sufficient_balance: boolean;
};

/* -------------------------------------------------------------------------
 * SMS Verifications marketplace
 * ---------------------------------------------------------------------- */

export type Availability = "AVAILABLE" | "LIMITED" | "UNAVAILABLE";

/** One service in one country, as the marketplace lists it. */
export type MarketRow = {
  slug: string;
  name: string;
  category: string;
  icon_url: string;
  accent_color: string;
  country?: string;
  price: string | null;
  currency?: string;
  supports_sms?: boolean;
  supports_voice?: boolean;
  maintenance_note?: string;
  availability: Availability;
  /** Only when the provider reported a plausible count; otherwise null. */
  available_count: number | null;
  pinned: boolean;
  /** A pin for a service not sold in this country at all. */
  unavailable_here?: boolean;
  /** Sold here, but cannot be bought right now. Only ever seen on a pin. */
  temporarily_unavailable?: boolean;
};

export type MarketCountry = {
  code: string;
  name: string;
  dial_code: string;
  flag_emoji: string;
};

export type MarketHome = {
  country: string;
  countries: MarketCountry[];
  voice_available: boolean;
  categories: { value: string; label: string }[];
  pinned: MarketRow[];
  popular: MarketRow[];
  total: number;
};

export type MarketPage = {
  results: MarketRow[];
  count: number;
  page: number;
  pages: number;
  has_next: boolean;
  country: string;
};

export type MarketServiceDetail = {
  slug: string;
  name: string;
  category: string;
  icon_url: string;
  accent_color: string;
  description: string;
  maintenance_note: string;
  pinned: boolean;
  countries: (MarketCountry & {
    offered: boolean;
    price?: string;
    currency?: string;
    availability: Availability;
    available_count?: number | null;
    temporarily_unavailable?: boolean;
  })[];
};

export type Eligibility = {
  eligible: boolean;
  code: string;
  message: string;
};

export type Notification = {
  id: string;
  event: string;
  title: string;
  body: string;
  is_read: boolean;
  read_at: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type Paginated<T> = {
  results: T[];
  pagination: {
    count: number;
    page: number;
    pages: number;
    page_size: number;
    has_next: boolean;
    has_previous: boolean;
  };
};

export type CatalogHealth = {
  ready: boolean;
  provider_configured: boolean;
  exchange_rate_configured: boolean;
  purchasable_offerings: number;
};

// -- admin -----------------------------------------------------------------

export type AdminOverview = {
  users: { total: number; active_30d: number; new_today: number; suspended: number };
  revenue: {
    total: string;
    today: string;
    provider_cost: string;
    gross_margin: string;
    margin_percent: string;
    currency: string;
  };
  orders: {
    total: number;
    today: number;
    successful: number;
    code_received: number;
    failed: number;
    active: number;
  };
  payments: { momo_total: string; momo_today: string; count: number; failed: number };
  refunds: { total: string; count: number };
  flags: { open: number; high: number };
};

export type AdminCharts = {
  days: number;
  revenue: { date: string; revenue: string; orders: number }[];
  orders: { date: string; total: number; successful: number; failed: number }[];
  popular_services: { slug: string; name: string; orders: number; revenue: string }[];
  payment_methods: { network: string; count: number; amount: string }[];
  failure_rate: number;
};

export type AdminUser = {
  id: string;
  email: string;
  full_name: string;
  phone: string;
  role: Role;
  is_active: boolean;
  is_suspended: boolean;
  suspension_reason: string;
  is_email_verified: boolean;
  is_phone_verified: boolean;
  risk_score: number;
  balance: string;
  order_count: number;
  open_flags: number;
  last_login: string | null;
  created_at: string;
};

export type IssueReason =
  | "NUMBER_ALREADY_LINKED"
  | "SMS_NOT_RECEIVED"
  | "OTP_DID_NOT_WORK"
  | "SERVICE_REJECTED_NUMBER"
  | "OTHER";

export type IssueStatus = "OPEN" | "IN_REVIEW" | "REFUNDED" | "REPLACED" | "REJECTED" | "RESOLVED";

/** A customer's report on their own order, as the customer sees it. */
export type OrderIssue = {
  reference: string;
  reason: IssueReason;
  reason_label: string;
  status: IssueStatus;
  status_label: string;
  message: string;
  replacement_order_reference: string | null;
  created_at: string;
};

export type AdminNumberIssue = {
  id: string;
  reference: string;
  order_reference: string;
  order_status: string;
  customer_id: string;
  customer_email: string;
  provider_name: string;
  provider_key: string;
  service_name: string;
  service_icon: string;
  country_code: string;
  number_masked: string;
  reason: IssueReason;
  reason_label: string;
  details: string;
  status: IssueStatus;
  status_label: string;
  qualifies: boolean;
  qualification: { check: string; ok: boolean }[];
  risk_flags: { code: string; detail: string }[];
  needs_review: boolean;
  resolution_note: string;
  resolved_by_email: string | null;
  resolved_at: string | null;
  replacement_order_reference: string | null;
  replacement_order_status: string | null;
  provider_report: "NOT_SUPPORTED" | "NOT_SENT" | "ACCEPTED" | "REFUSED";
  price: string;
  refund: { reference: string; amount: string; reason: string; status: string } | null;
  created_at: string;
};

export type AdminNumberIssueDetail = AdminNumberIssue & {
  history: {
    quality: string;
    quality_label: string;
    times_issued: number;
    reports: number;
    other_reports_by_other_customers: number;
    first_issued_at: string | null;
    by_service: {
      service: string;
      quality: string;
      quality_label: string;
      times_issued: number;
      reports: number;
    }[];
    usages: {
      order: string;
      disposition: string;
      acquired_at: string;
      assigned_at: string | null;
      sms_received_at: string | null;
      same_customer: boolean;
    }[];
    provider_history_available: boolean;
  } | null;
  timeline: {
    acquired_at: string | null;
    assigned_at: string | null;
    sms_received_at: string | null;
    completed_at: string | null;
    reported_at: string;
    refund_status: string;
  };
  customer: {
    joined: string;
    orders: number;
    orders_with_code: number;
    reports: number;
    remedies: number;
  };
};

export type NumberIssueBreakdown = {
  name: string;
  delivered: number;
  possible_reuse_reports: number;
  reported_rate_percent: number | null;
};

export type NumberIssueMetrics = {
  days: number;
  numbers_purchased: number;
  sms_received: number;
  reports_total: number;
  reports_by_reason: Record<IssueReason, number>;
  possible_reuse_reports: number;
  possible_reuse_rate_percent: number | null;
  open_cases: number;
  needs_review: number;
  refunded_orders: number;
  refunded_amount: string;
  replacement_orders: number;
  rejected: number;
  numbers_turned_away: number;
  flagged_numbers: number;
  by_provider: NumberIssueBreakdown[];
  by_service: NumberIssueBreakdown[];
  note: string;
};

export type AdminOrder = {
  id: string;
  reference: string;
  /** The pricing snapshot frozen at purchase (see PriceQuote); older orders hold fewer fields. */
  price_breakdown?: Partial<PriceQuote> & { applied?: Record<string, string | boolean> };
  user_id: string;
  user_email: string;
  service_name: string;
  service_icon: string;
  country_code: string;
  country_dial_code: string;
  provider_name: string;
  provider_order_id: string;
  phone_number: string;
  price: string;
  currency: string;
  provider_cost: string;
  provider_currency: string;
  exchange_rate: string;
  status: OrderStatus;
  refund_status: string;
  failure_reason: string;
  has_code: boolean;
  expires_at: string | null;
  completed_at: string | null;
  created_at: string;
};

export type AdminSystemHealth = {
  verification_provider: { key: string; healthy: boolean; is_mock: boolean };
  payment_provider: { key: string; healthy: boolean; is_mock: boolean };
  exchange_rate: {
    configured: boolean;
    rate: string | null;
    fetched_at: string | null;
    source: string | null;
  };
  pricing_rules: number;
  providers: {
    name: string;
    adapter_key: string;
    is_enabled: boolean;
    last_synced_at: string | null;
    last_sync_error: string;
  }[];
  unprocessed_webhooks: number;
};

export type AdminPayment = {
  id: string;
  reference: string;
  user_email: string;
  provider: string;
  provider_reference: string;
  amount: string;
  currency: string;
  network: string;
  status: PaymentStatus;
  failure_reason: string;
  credited_at: string | null;
  completed_at: string | null;
  created_at: string;
};

export type AdminOffering = {
  id: string;
  provider_name: string;
  service_name: string;
  service_slug: string;
  service_icon: string;
  country_code: string;
  provider_service_code: string;
  cost_amount: string;
  cost_currency: string;
  /** Provider cost converted to cedis at the current rate. */
  base_cost: string | null;
  /** The lowest price that still covers cost and the collection fee. */
  cost_floor: string | null;
  customer_price: string | null;
  margin: string | null;
  pricing_rule_name: string;
  pricing_error: string;
  is_enabled: boolean;
  is_available: boolean;
  available_count: number | null;
  supports_sms: boolean;
  supports_voice: boolean;
  ttl_minutes: number;
  last_synced_at: string | null;
  price_updated_at: string | null;
};

export type PriceChange = {
  id: string;
  service_name: string;
  country_code: string;
  provider_key: string;
  old_price: string | null;
  new_price: string;
  currency: string;
  provider_cost: string;
  provider_currency: string;
  exchange_rate: string;
  pricing_rule_name: string;
  source: "PRICING_RULE" | "PROVIDER_COST" | "EXCHANGE_RATE" | "INITIAL";
  source_label: string;
  changed_by_email: string | null;
  reason: string;
  created_at: string;
};

export type AdminService = {
  id: string;
  slug: string;
  name: string;
  category: ServiceCategory;
  description: string;
  accent_color: string;
  icon_url: string;
  has_uploaded_logo: boolean;
  bundled_icon_url: string;
  aliases: string;
  is_popular: boolean;
  popular_rank: number;
  is_enabled: boolean;
  is_maintenance: boolean;
  maintenance_note: string;
  supports_sms: boolean;
  supports_voice: boolean;
  display_order: number;
  offering_count: number;
  available_count: number;
  /** Offerings in the marketplace countries: 0 means not sold to customers. */
  marketplace_offerings: number;
};

export type AdminCountry = {
  id: string;
  code: string;
  name: string;
  dial_code: string;
  flag_emoji: string;
  is_enabled: boolean;
  display_order: number;
};

export type PricingRule = {
  id: string;
  name: string;
  is_active: boolean;
  service: string | null;
  service_slug: string | null;
  service_name: string | null;
  country: string | null;
  country_code: string | null;
  provider: string | null;
  provider_key: string | null;
  markup_type: "PERCENTAGE" | "FIXED" | "HYBRID";
  markup_percent: string;
  markup_fixed: string;
  payment_fee_percent: string;
  risk_buffer_percent: string;
  rounding: string;
  min_price: string;
  max_price: string;
  allow_below_cost: boolean;
  priority: number;
  created_at: string;
  updated_at: string;
};

export type ExchangeRate = {
  id: number;
  base_currency: string;
  quote_currency: string;
  rate: string;
  source: string;
  note: string;
  is_active: boolean;
  fetched_at: string;
};

export type SuspiciousActivity = {
  id: string;
  user: string | null;
  user_email: string;
  kind: string;
  level: "LOW" | "MEDIUM" | "HIGH";
  description: string;
  evidence: Record<string, unknown>;
  resolved: boolean;
  resolved_at: string | null;
  resolution_note: string;
  created_at: string;
};

export type AuditLogEntry = {
  id: string;
  actor_email: string;
  action: string;
  target_type: string;
  target_id: string;
  ip_address: string | null;
  request_id: string;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type AdminActionEntry = {
  id: string;
  admin_email: string;
  action: string;
  target_type: string;
  target_id: string;
  reason: string;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  created_at: string;
};

// ---------------------------------------------------------------------------
// Referrals
// ---------------------------------------------------------------------------

export type ReferralStats = {
  successful: number;
  pending: number;
  rejected: number;
  total: number;
  rewards_issued: string;
};

export type MyReferral = {
  enabled: boolean;
  code: string;
  share_url: string;
  bonus_amount: string;
  currency: string;
  stats: ReferralStats;
};

/** What a referrer may see about someone they invited: no name, no address. */
export type ReferralHistoryItem = {
  friend: string;
  status: "PENDING" | "REWARDED" | "REJECTED";
  reward_amount: string | null;
  created_at: string;
  rewarded_at: string | null;
};

export type ReferralRiskFlag = {
  kind: string;
  level: "LOW" | "MEDIUM" | "HIGH";
  detail: string;
  blocking: boolean;
  created_at: string;
};

export type AdminReferral = {
  id: string;
  code: string;
  status: "PENDING" | "ELIGIBLE" | "REWARDED" | "REJECTED" | "FRAUD_FLAGGED";
  reason: string;
  staff_note: string;
  referrer_id: string;
  referrer_email: string;
  referred_id: string;
  referred_email: string;
  referred_email_verified: boolean;
  referred_suspended: boolean;
  signup_ip: string | null;
  risk_score: number;
  reward: {
    reference: string;
    amount: string;
    currency: string;
    status: "ISSUED" | "REVERSED";
    ledger_entry_id: string | null;
    reversed_at: string | null;
    created_at: string;
  } | null;
  risk_flags: ReferralRiskFlag[];
  created_at: string;
  eligible_at: string | null;
  rewarded_at: string | null;
  rejected_at: string | null;
};

export type ReferralAnalytics = {
  registrations: number;
  pending: number;
  eligible: number;
  rewarded: number;
  rejected: number;
  fraud_flagged: number;
  promotional_credit_issued: string;
  promotional_credit_reversed: string;
  average_acquisition_cost: string;
  conversion_rate: number;
};

/* -------------------------------------------------------------------------
 * Admin > Pricing
 * ---------------------------------------------------------------------- */

export type PricingStatus =
  | "ACTIVE"
  | "INACTIVE"
  | "OUT_OF_STOCK"
  | "NOT_SOLD"
  | "NOT_SYNCED";

export type PricingRow = {
  id: string;
  service: { slug: string; name: string; icon_url: string };
  country: { code: string; name: string; flag: string };
  provider: { key: string; name: string; demo: boolean };
  /** Exactly what the provider reported (or staff entered); null = not synced. */
  provider_cost: string | null;
  currency: string;
  cost_source: "PROVIDER_API" | "MANUAL" | "NOT_SYNCED";
  status: PricingStatus;
  is_enabled: boolean;
  is_available: boolean;
  price_review_pending: boolean;
  fx_rate?: string;
  fx_mode?: string;
  ghs_cost?: string;
  markup?: string;
  markup_type?: string;
  markup_percent_effective?: string;
  calculated_price?: string;
  override_price?: string | null;
  recommended_price?: string;
  /** What customers pay now; null when it is not sold. */
  customer_price?: string | null;
  gross_profit?: string;
  gross_margin_percent?: string;
  below_minimum_margin?: boolean;
  is_loss?: boolean;
  rule?: string;
};

/** The engine's full breakdown (Quote.as_dict). */
export type PriceQuote = {
  customer_price: string;
  currency: string;
  provider_cost: string;
  provider_currency: string;
  cost_source: string;
  exchange_rate: string;
  market_rate: string | null;
  fx_mode: string;
  fx_adjustment_percent: string;
  base_cost: string;
  markup: string;
  payment_fee: string;
  risk_buffer: string;
  raw_price: string;
  calculated_price: string;
  override_price: string | null;
  override_reason: string;
  recommended_price: string;
  published_price: string | null;
  pending_review: boolean;
  below_minimum_margin: boolean;
  minimum_margin_percent: string;
  pricing_rule_name: string;
  applied: Record<string, string | boolean>;
  gross_profit: string;
  gross_margin_percent: string;
  markup_percent_effective: string;
  is_loss: boolean;
  quoted_at: string | null;
};

export type PricingSummary = {
  total_services: number;
  total_offerings: number;
  active_offerings: number;
  average_markup_percent: string | null;
  average_gross_margin_percent: string | null;
  below_minimum_margin: number;
  not_sold: number;
  not_synced: number;
  pending_review: number;
  active_overrides: number;
  fx: {
    currency: string;
    pricing_rate?: string;
    mode?: string;
    market_rate?: string | null;
    adjustment_percent?: string;
    error?: string;
  }[];
  policy: PricingPolicyData;
  providers: { key: string; name: string; demo: boolean }[];
};

export type PricingPolicyData = {
  minimum_margin_percent: string;
  enforce_minimum_margin: boolean;
  auto_publish_prices: boolean;
  updated_at: string | null;
};

export type PricingOfferingDetail = {
  row: PricingRow;
  published: PriceQuote | null;
  recommended: PriceQuote | null;
  rule: {
    id: string;
    name: string;
    scope: { service: string | null; country: string | null; provider: string | null };
    markup_type: "PERCENTAGE" | "FIXED" | "HYBRID";
    markup_percent: string;
    markup_fixed: string;
  } | null;
  cost_editable: boolean;
  overrides: {
    price: string;
    reason: string;
    allow_loss: boolean;
    is_active: boolean;
    created_by: string | null;
    created_at: string;
    ended_by: string | null;
    ended_at: string | null;
    end_reason: string;
  }[];
  cost_history: {
    old: string | null;
    new: string;
    currency: string;
    source: string;
    sync_method: string;
    by: string | null;
    reason: string;
    at: string;
  }[];
  price_history: {
    old: string | null;
    new: string;
    source: string;
    by: string | null;
    reason: string;
    at: string;
  }[];
  provider_comparison: {
    providers: {
      provider: string;
      provider_key: string;
      cost: string | null;
      currency: string;
      ghs_cost: string | null;
      available: boolean;
      enabled: boolean;
      priority: number;
      this: boolean;
    }[];
    lowest_available_ghs_cost: string | null;
    routing: string;
  };
};

export type PricingPreview = {
  quote: PriceQuote;
  warnings: ("LOSS_MAKING" | "BELOW_MINIMUM_MARGIN")[];
  enforce_minimum_margin: boolean;
};

export type PricingImpact = {
  offerings: number;
  changed: number;
  unsellable: number;
  below_minimum_margin: number;
  average_change: string;
  average_gross_margin_after: string | null;
  examples: { service: string; country: string; before: string; after: string; gross_margin_after: string }[];
  below_minimum_examples: string[];
  governed_by_this_rule?: number;
  keep_their_own_rule?: number;
  pricing_rate?: string;
  market_rate?: string | null;
};

export type PricingFXRow = {
  currency: string;
  mode: "MANUAL" | "AUTOMATIC" | "MARKET";
  manual_rate: string | null;
  adjustment_percent: string;
  effective_rate: string | null;
  error: string;
  market_rate: string | null;
  market_rate_source: string | null;
  market_rate_at: string | null;
  updated_by: string | null;
  updated_at: string | null;
};

export type ProviderCostChangeRow = {
  id: string;
  service_name: string;
  country_code: string;
  provider_key: string;
  old_cost: string | null;
  new_cost: string;
  currency: string;
  source: "PROVIDER_API" | "MANUAL";
  sync_method: string;
  changed_by_email: string | null;
  reason: string;
  created_at: string;
};

export type PricingAuditRow = {
  id: string;
  admin_email: string | null;
  action: string;
  reason: string;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  created_at: string;
};
