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

export type PaymentStatus =
  | "PENDING"
  | "PROCESSING"
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
  provider_cost: string;
  provider_currency: string;
  exchange_rate: string;
  failure_reason: string;
  verification_code: string;
  verification_message: string;
  code_display_allowed: boolean;
  code_received_at: string | null;
  completed_at: string | null;
  seconds_remaining: number;
  can_cancel: boolean;
  can_complete: boolean;
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
  available_count: number | null;
  offering_id: string;
  wallet_balance: string;
  sufficient_balance: boolean;
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

export type AdminOrder = {
  id: string;
  reference: string;
  user_id: string;
  user_email: string;
  service_name: string;
  country_code: string;
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
  country_code: string;
  provider_service_code: string;
  cost_amount: string;
  cost_currency: string;
  customer_price: string | null;
  margin: string | null;
  pricing_error: string;
  is_enabled: boolean;
  is_available: boolean;
  available_count: number | null;
  supports_sms: boolean;
  supports_voice: boolean;
  ttl_minutes: number;
  last_synced_at: string | null;
};

export type AdminService = {
  id: string;
  slug: string;
  name: string;
  category: ServiceCategory;
  description: string;
  accent_color: string;
  icon_url: string;
  is_enabled: boolean;
  is_maintenance: boolean;
  maintenance_note: string;
  supports_sms: boolean;
  supports_voice: boolean;
  display_order: number;
  offering_count: number;
  available_count: number;
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
  country: string | null;
  country_code: string | null;
  markup_type: "PERCENTAGE" | "FIXED" | "HYBRID";
  markup_percent: string;
  markup_fixed: string;
  payment_fee_percent: string;
  risk_buffer_percent: string;
  rounding: string;
  min_price: string;
  max_price: string;
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
