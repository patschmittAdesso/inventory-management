<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div v-if="loading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else>
      <div class="card budget-card">
        <div class="budget-header">
          <div>
            <h3 class="card-title">{{ t('restocking.budgetTitle') }}</h3>
            <p class="budget-hint">{{ t('restocking.budgetHint') }}</p>
          </div>
          <div class="budget-amount">{{ formatWhole(budget) }}</div>
        </div>
        <input
          v-model.number="budget"
          type="range"
          class="budget-slider"
          min="0"
          :max="maxBudget"
          step="100"
          :aria-label="t('restocking.budgetTitle')"
          @input="scheduleRefresh"
        />
        <div class="budget-scale">
          <span>{{ formatWhole(0) }}</span>
          <span>{{ formatWhole(maxBudget) }}</span>
        </div>
      </div>

      <div class="stats-grid">
        <div class="stat-card info">
          <div class="stat-label">{{ t('restocking.stats.budget') }}</div>
          <div class="stat-value">{{ formatWhole(appliedBudget) }}</div>
        </div>
        <div class="stat-card warning">
          <div class="stat-label">{{ t('restocking.stats.selectedCost') }}</div>
          <div class="stat-value">{{ formatMoney(selectedCost) }}</div>
        </div>
        <div class="stat-card success">
          <div class="stat-label">{{ t('restocking.stats.remainingBudget') }}</div>
          <div class="stat-value">{{ formatMoney(remainingBudget) }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">{{ t('restocking.stats.longestLeadTime') }}</div>
          <div class="stat-value">{{ t('restocking.days', { count: longestLeadTime }) }}</div>
        </div>
      </div>

      <div v-if="lastOrder" class="success-message" role="status">
        <span>
          {{ t('restocking.orderSuccess', {
            number: lastOrder.order_number,
            days: lastOrder.lead_time_days,
            date: formatDate(lastOrder.expected_delivery)
          }) }}
        </span>
        <router-link to="/orders" class="success-link">{{ t('restocking.viewOrders') }}</router-link>
      </div>
      <div v-if="orderError" class="error" role="alert">{{ orderError }}</div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.recommendedItems') }}</h3>
          <span class="selected-count">
            {{ t('restocking.selectedCount', { selected: selectedItems.length, total: items.length }) }}
          </span>
        </div>

        <div v-if="items.length === 0" class="empty-state">{{ t('restocking.noItems') }}</div>
        <div v-else class="table-container">
          <table class="restock-table">
            <thead>
              <tr>
                <th class="col-select">{{ t('restocking.table.select') }}</th>
                <th>{{ t('restocking.table.item') }}</th>
                <th>{{ t('restocking.table.trend') }}</th>
                <th class="num">{{ t('restocking.table.forecast') }}</th>
                <th class="num">{{ t('restocking.table.stock') }}</th>
                <th class="num">{{ t('restocking.table.quantity') }}</th>
                <th class="num">{{ t('restocking.table.unitCost') }}</th>
                <th class="num">{{ t('restocking.table.lineTotal') }}</th>
                <th class="num">{{ t('restocking.table.leadTime') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in items" :key="item.item_sku">
                <td class="col-select">
                  <input
                    v-model="selectedSkus"
                    type="checkbox"
                    :value="item.item_sku"
                    :aria-label="item.item_sku"
                  />
                </td>
                <td>
                  <strong>{{ item.item_sku }}</strong>
                  <div class="item-subtitle">{{ translateProductName(item.item_name) }}</div>
                </td>
                <td>
                  <span :class="['badge', item.trend]">{{ t(`trends.${item.trend}`) }}</span>
                </td>
                <td class="num">{{ item.forecasted_demand.toLocaleString() }}</td>
                <td class="num">{{ item.current_stock.toLocaleString() }}</td>
                <td class="num"><strong>{{ item.recommended_qty.toLocaleString() }}</strong></td>
                <td class="num">{{ formatMoney(item.unit_cost) }}</td>
                <td class="num"><strong>{{ formatMoney(item.line_total) }}</strong></td>
                <td class="num">{{ t('restocking.days', { count: item.lead_time_days }) }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="card-footer">
          <button
            type="button"
            class="place-order"
            :disabled="!canPlaceOrder"
            @click="placeOrder"
          >
            {{ submitting ? t('restocking.placingOrder') : t('restocking.placeOrder') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'

const DEBOUNCE_MS = 250
const SLIDER_STEP = 100

export default {
  name: 'Restocking',
  setup() {
    const { t, currentLocale, currentCurrency, translateProductName } = useI18n()

    const currencySymbol = computed(() => (currentCurrency.value === 'JPY' ? '¥' : '$'))

    const loading = ref(true)
    const error = ref(null)
    const orderError = ref(null)
    const lastOrder = ref(null)
    const submitting = ref(false)
    // True from the first slider move until the matching response arrives
    const refreshing = ref(false)

    const budget = ref(0)
    const maxBudget = ref(0)
    const recommendation = ref(null)
    const selectedSkus = ref([])

    const items = computed(() => recommendation.value?.items ?? [])
    // The budget the shown recommendation was computed for; the slider can be ahead of it while debouncing
    const appliedBudget = computed(() => recommendation.value?.budget ?? 0)

    const selectedItems = computed(() => items.value.filter(i => selectedSkus.value.includes(i.item_sku)))
    const selectedCost = computed(() => selectedItems.value.reduce((sum, i) => sum + i.line_total, 0))
    const remainingBudget = computed(() => appliedBudget.value - selectedCost.value)
    const longestLeadTime = computed(() => Math.max(0, ...selectedItems.value.map(i => i.lead_time_days)))

    const canPlaceOrder = computed(() => selectedItems.value.length > 0 && !submitting.value && !refreshing.value)

    const formatWhole = (value) => `${currencySymbol.value}${Math.round(value).toLocaleString()}`
    const formatMoney = (value) => `${currencySymbol.value}${value.toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    })}`
    const formatDate = (dateString) => {
      const date = new Date(dateString)
      if (isNaN(date.getTime())) return ''
      return date.toLocaleDateString(currentLocale.value === 'ja' ? 'ja-JP' : 'en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric'
      })
    }

    // Monotonic id so a slow earlier response can never overwrite a newer one
    let requestId = 0
    let debounceTimer = null

    const fetchRecommendation = async (budgetValue) => {
      const id = ++requestId
      try {
        const result = await api.getRestockRecommendations(budgetValue)
        if (id !== requestId) return
        recommendation.value = result
        selectedSkus.value = result.items.map(i => i.item_sku)
        orderError.value = null
      } catch (err) {
        if (id !== requestId) return
        const message = t('restocking.loadError') + ': ' + err.message
        // Only a failed first load replaces the page; later refresh failures stay inline so the slider remains usable
        if (recommendation.value) {
          orderError.value = message
        } else {
          error.value = message
        }
        console.error('Recommendation error:', err)
      } finally {
        if (id === requestId) refreshing.value = false
      }
    }

    const scheduleRefresh = () => {
      refreshing.value = true
      clearTimeout(debounceTimer)
      debounceTimer = setTimeout(() => fetchRecommendation(budget.value), DEBOUNCE_MS)
    }

    const loadInitial = async () => {
      try {
        loading.value = true
        // Budget 0 is the cheapest call that still returns full_restock_cost, which defines the slider range
        const probe = await api.getRestockRecommendations(0)
        maxBudget.value = Math.max(SLIDER_STEP, Math.ceil(probe.full_restock_cost / 1000) * 1000)
        budget.value = Math.round(maxBudget.value / 2 / SLIDER_STEP) * SLIDER_STEP
        await fetchRecommendation(budget.value)
      } catch (err) {
        error.value = t('restocking.loadError') + ': ' + err.message
        console.error('Restocking load error:', err)
      } finally {
        loading.value = false
      }
    }

    const placeOrder = async () => {
      if (!canPlaceOrder.value) return
      submitting.value = true
      orderError.value = null
      lastOrder.value = null
      try {
        // Send the budget the recommendation was built for, not the live slider value, so the server check matches what the user saw
        lastOrder.value = await api.submitRestockOrder({
          budget: appliedBudget.value,
          items: selectedItems.value.map(i => ({ item_sku: i.item_sku, quantity: i.recommended_qty }))
        })
        await fetchRecommendation(appliedBudget.value)
      } catch (err) {
        orderError.value = err.response?.data?.detail || err.message
        console.error('Place order error:', err)
      } finally {
        submitting.value = false
      }
    }

    onMounted(loadInitial)
    onBeforeUnmount(() => clearTimeout(debounceTimer))

    return {
      t,
      loading,
      error,
      orderError,
      lastOrder,
      submitting,
      budget,
      maxBudget,
      items,
      appliedBudget,
      selectedSkus,
      selectedItems,
      selectedCost,
      remainingBudget,
      longestLeadTime,
      canPlaceOrder,
      formatWhole,
      formatMoney,
      formatDate,
      scheduleRefresh,
      placeOrder,
      translateProductName
    }
  }
}
</script>

<style scoped>
.budget-card {
  padding: 1.5rem;
}

.budget-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 1rem;
  margin-bottom: 1.25rem;
}

.budget-hint {
  margin-top: 0.25rem;
  color: #64748b;
  font-size: 0.875rem;
}

.budget-amount {
  font-size: 2.25rem;
  font-weight: 700;
  color: #0f172a;
  letter-spacing: -0.025em;
  white-space: nowrap;
}

.budget-slider {
  -webkit-appearance: none;
  appearance: none;
  width: 100%;
  height: 8px;
  border-radius: 999px;
  background: #e2e8f0;
  outline: none;
  cursor: pointer;
}

.budget-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: #0f172a;
  border: 3px solid white;
  box-shadow: 0 1px 4px rgba(15, 23, 42, 0.4);
  transition: transform 0.15s ease;
}

.budget-slider::-webkit-slider-thumb:hover {
  transform: scale(1.1);
}

.budget-slider::-moz-range-track {
  height: 8px;
  border-radius: 999px;
  background: #e2e8f0;
}

.budget-slider::-moz-range-thumb {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #0f172a;
  border: 3px solid white;
  box-shadow: 0 1px 4px rgba(15, 23, 42, 0.4);
}

.budget-slider:focus-visible::-webkit-slider-thumb {
  outline: 2px solid #3b82f6;
  outline-offset: 2px;
}

.budget-slider:focus-visible::-moz-range-thumb {
  outline: 2px solid #3b82f6;
  outline-offset: 2px;
}

.budget-scale {
  display: flex;
  justify-content: space-between;
  margin-top: 0.5rem;
  color: #64748b;
  font-size: 0.813rem;
}

.selected-count {
  color: #64748b;
  font-size: 0.875rem;
}

.col-select {
  width: 70px;
  text-align: center;
}

.restock-table th.num,
.restock-table td.num {
  text-align: right;
  white-space: nowrap;
}

.item-subtitle {
  color: #64748b;
  font-size: 0.813rem;
}

.empty-state {
  padding: 2rem;
  text-align: center;
  color: #64748b;
  font-size: 0.938rem;
}

.card-footer {
  display: flex;
  justify-content: flex-end;
  margin-top: 1rem;
  padding-top: 1rem;
  border-top: 1px solid #e2e8f0;
}

.place-order {
  padding: 0.625rem 1.5rem;
  border: none;
  border-radius: 6px;
  background: #0f172a;
  color: white;
  font-size: 0.938rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.place-order:hover:not(:disabled) {
  background: #1e293b;
}

.place-order:disabled {
  background: #cbd5e1;
  cursor: not-allowed;
}

.success-message {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
  background: #d1fae5;
  border: 1px solid #a7f3d0;
  color: #065f46;
  padding: 1rem;
  border-radius: 8px;
  margin-bottom: 1.25rem;
  font-size: 0.938rem;
}

.success-link {
  color: #065f46;
  font-weight: 600;
  white-space: nowrap;
}
</style>