<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="isOpen && backlogItem" class="modal-overlay" @click="close">
        <div class="modal-container" @click.stop>
          <div class="modal-header">
            <h3 class="modal-title">
              {{ mode === 'view' ? t('purchaseOrder.viewTitle') : t('purchaseOrder.createTitle') }}
            </h3>
            <button class="close-button" :aria-label="t('common.close')" @click="close">
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                <path d="M15 5L5 15M5 5L15 15" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
              </svg>
            </button>
          </div>

          <div class="modal-body">
            <div class="item-summary">
              <div class="item-name">{{ translateProductName(backlogItem.item_name) }}</div>
              <div class="item-meta">
                <span>{{ t('purchaseOrder.sku') }}: {{ backlogItem.item_sku }}</span>
                <span>{{ t('purchaseOrder.shortage') }}: {{ shortage }} {{ t('purchaseOrder.units') }}</span>
              </div>
            </div>

            <!-- Create mode -->
            <form v-if="mode === 'create'" id="po-form" class="po-form" novalidate @submit.prevent="submit">
              <div class="form-field">
                <label for="po-supplier">{{ t('purchaseOrder.supplierName') }}</label>
                <input id="po-supplier" v-model="form.supplier_name" type="text" :class="{ invalid: fieldErrors.supplier_name }" />
                <span v-if="fieldErrors.supplier_name" class="field-error">{{ fieldErrors.supplier_name }}</span>
              </div>

              <div class="form-row">
                <div class="form-field">
                  <label for="po-quantity">{{ t('purchaseOrder.quantity') }}</label>
                  <input id="po-quantity" v-model="form.quantity" type="number" min="1" step="1" :class="{ invalid: fieldErrors.quantity }" />
                  <span v-if="fieldErrors.quantity" class="field-error">{{ fieldErrors.quantity }}</span>
                </div>

                <div class="form-field">
                  <label for="po-unit-cost">{{ t('purchaseOrder.unitCost') }}</label>
                  <input id="po-unit-cost" v-model="form.unit_cost" type="number" min="0" step="0.01" :class="{ invalid: fieldErrors.unit_cost }" />
                  <span v-if="fieldErrors.unit_cost" class="field-error">{{ fieldErrors.unit_cost }}</span>
                </div>
              </div>

              <div class="form-field">
                <label for="po-date">{{ t('purchaseOrder.expectedDeliveryDate') }}</label>
                <input id="po-date" v-model="form.expected_delivery_date" type="date" :class="{ invalid: fieldErrors.expected_delivery_date }" />
                <span v-if="fieldErrors.expected_delivery_date" class="field-error">{{ fieldErrors.expected_delivery_date }}</span>
              </div>

              <div class="form-field">
                <label for="po-notes">{{ t('purchaseOrder.notes') }}</label>
                <textarea id="po-notes" v-model="form.notes" rows="3" :placeholder="t('purchaseOrder.notesPlaceholder')"></textarea>
              </div>

              <div v-if="submitError" class="error-banner" role="alert">{{ submitError }}</div>
            </form>

            <!-- View mode -->
            <template v-else>
              <div v-if="viewLoading" class="state-message">{{ t('purchaseOrder.loading') }}</div>
              <div v-else-if="viewError" class="error-banner" role="alert">{{ viewError }}</div>
              <div v-else-if="po" class="info-grid">
                <div class="info-item">
                  <div class="info-label">{{ t('purchaseOrder.poNumber') }}</div>
                  <div class="info-value mono">{{ po.id }}</div>
                </div>
                <div class="info-item">
                  <div class="info-label">{{ t('purchaseOrder.status') }}</div>
                  <div class="info-value"><span class="badge" :class="statusClass">{{ po.status }}</span></div>
                </div>
                <div class="info-item">
                  <div class="info-label">{{ t('purchaseOrder.supplierName') }}</div>
                  <div class="info-value">{{ po.supplier_name }}</div>
                </div>
                <div class="info-item">
                  <div class="info-label">{{ t('purchaseOrder.quantity') }}</div>
                  <div class="info-value">{{ po.quantity }} {{ t('purchaseOrder.units') }}</div>
                </div>
                <div class="info-item">
                  <div class="info-label">{{ t('purchaseOrder.unitCost') }}</div>
                  <div class="info-value">{{ formatUsd(po.unit_cost) }}</div>
                </div>
                <div class="info-item">
                  <div class="info-label">{{ t('purchaseOrder.totalCost') }}</div>
                  <div class="info-value">{{ formatUsd(poTotal) }}</div>
                </div>
                <div class="info-item">
                  <div class="info-label">{{ t('purchaseOrder.expectedDeliveryDate') }}</div>
                  <div class="info-value">{{ formatDate(po.expected_delivery_date) }}</div>
                </div>
                <div class="info-item">
                  <div class="info-label">{{ t('purchaseOrder.createdDate') }}</div>
                  <div class="info-value">{{ formatDate(po.created_date) }}</div>
                </div>
                <div class="info-item full-width">
                  <div class="info-label">{{ t('purchaseOrder.notes') }}</div>
                  <div class="info-value">{{ po.notes || t('purchaseOrder.noNotes') }}</div>
                </div>
              </div>
            </template>
          </div>

          <div class="modal-footer">
            <button class="btn-secondary" type="button" @click="close">
              {{ mode === 'view' ? t('common.close') : t('common.cancel') }}
            </button>
            <button v-if="mode === 'create'" class="btn-primary" type="submit" form="po-form" :disabled="submitting">
              {{ submitting ? t('purchaseOrder.submitting') : t('purchaseOrder.submit') }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, reactive, computed, watch } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'

const { t, currentLocale, translateProductName } = useI18n()

const props = defineProps({
  isOpen: { type: Boolean, default: false },
  backlogItem: { type: Object, default: null },
  mode: { type: String, default: 'create', validator: (v) => ['create', 'view'].includes(v) }
})

const emit = defineEmits(['close', 'po-created'])

const emptyForm = () => ({
  supplier_name: '',
  quantity: '',
  unit_cost: '',
  expected_delivery_date: '',
  notes: ''
})

const form = reactive(emptyForm())
const fieldErrors = reactive({})
const submitting = ref(false)
const submitError = ref(null)

const po = ref(null)
const viewLoading = ref(false)
const viewError = ref(null)

// Guards against a slow response from a previously opened item overwriting the current one
let viewRequestId = 0

const shortage = computed(() => {
  if (!props.backlogItem) return 0
  return Math.max(props.backlogItem.quantity_needed - props.backlogItem.quantity_available, 0)
})

const poTotal = computed(() => (po.value ? Number(po.value.quantity) * Number(po.value.unit_cost) : 0))

const statusClass = computed(() => {
  const s = (po.value?.status || '').toLowerCase()
  if (['delivered', 'received', 'completed'].includes(s)) return 'success'
  if (['cancelled', 'canceled', 'rejected'].includes(s)) return 'danger'
  if (['pending', 'ordered', 'in_transit', 'shipped'].includes(s)) return 'info'
  return 'neutral'
})

const resetForm = () => {
  Object.assign(form, emptyForm())
  // Default to the shortage so the user orders exactly what is missing
  form.quantity = shortage.value > 0 ? shortage.value : ''
  Object.keys(fieldErrors).forEach((k) => delete fieldErrors[k])
  submitError.value = null
  submitting.value = false
}

const loadPO = async () => {
  const requestId = ++viewRequestId
  po.value = null
  viewError.value = null

  if (props.backlogItem.purchase_order) {
    po.value = props.backlogItem.purchase_order
    viewLoading.value = false
    return
  }

  viewLoading.value = true
  try {
    const data = await api.getPurchaseOrderByBacklogItem(props.backlogItem.id)
    if (requestId !== viewRequestId) return
    po.value = data
  } catch (err) {
    if (requestId !== viewRequestId) return
    viewError.value = err.response?.status === 404
      ? t('purchaseOrder.notFound')
      : (err.response?.data?.detail || t('purchaseOrder.loadError'))
    console.error(err)
  } finally {
    if (requestId === viewRequestId) viewLoading.value = false
  }
}

// Re-initialise on every open (and when the item/mode changes while open)
watch(
  () => [props.isOpen, props.backlogItem?.id, props.mode],
  () => {
    if (!props.isOpen || !props.backlogItem) {
      viewRequestId++ // invalidate in-flight loads when closing
      return
    }
    if (props.mode === 'view') loadPO()
    else resetForm()
  },
  { immediate: true }
)

const validate = () => {
  Object.keys(fieldErrors).forEach((k) => delete fieldErrors[k])

  if (!form.supplier_name.trim()) fieldErrors.supplier_name = t('purchaseOrder.errors.supplierRequired')

  const qty = Number(form.quantity)
  if (form.quantity === '' || form.quantity === null || !Number.isInteger(qty) || qty <= 0) {
    fieldErrors.quantity = t('purchaseOrder.errors.quantityInvalid')
  }

  const cost = Number(form.unit_cost)
  if (form.unit_cost === '' || form.unit_cost === null || !Number.isFinite(cost) || cost < 0) {
    fieldErrors.unit_cost = t('purchaseOrder.errors.unitCostInvalid')
  }

  if (!form.expected_delivery_date) fieldErrors.expected_delivery_date = t('purchaseOrder.errors.dateRequired')

  return Object.keys(fieldErrors).length === 0
}

const submit = async () => {
  if (submitting.value || !validate()) return

  submitting.value = true
  submitError.value = null
  try {
    const created = await api.createPurchaseOrder({
      backlog_item_id: props.backlogItem.id,
      supplier_name: form.supplier_name.trim(),
      quantity: Number(form.quantity),
      unit_cost: Number(form.unit_cost),
      expected_delivery_date: form.expected_delivery_date,
      notes: form.notes.trim()
    })
    emit('po-created', created)
  } catch (err) {
    // FastAPI validation errors return detail as an array; only show plain strings directly
    const detail = err.response?.data?.detail
    submitError.value = typeof detail === 'string' ? detail : t('purchaseOrder.createError')
    console.error(err)
  } finally {
    submitting.value = false
  }
}

const close = () => emit('close')

const formatDate = (value) => {
  if (!value) return 'N/A'
  const date = new Date(value)
  if (isNaN(date.getTime())) return value
  return date.toLocaleDateString(currentLocale.value === 'ja' ? 'ja-JP' : 'en-US', {
    year: 'numeric',
    month: 'long',
    day: 'numeric'
  })
}

// Unit cost is entered and stored in USD, so display it in USD (no locale currency conversion)
const formatUsd = (amount) =>
  `$${Number(amount).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2000;
  padding: 1rem;
}

.modal-container {
  background: white;
  border-radius: 12px;
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.15);
  max-width: 600px;
  width: 100%;
  max-height: 90vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1.5rem;
  border-bottom: 1px solid #e2e8f0;
}

.modal-title {
  font-size: 1.25rem;
  font-weight: 700;
  color: #0f172a;
  letter-spacing: -0.025em;
}

.close-button {
  background: none;
  border: none;
  color: #64748b;
  cursor: pointer;
  padding: 0.5rem;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  transition: all 0.15s ease;
}

.close-button:hover {
  background: #f1f5f9;
  color: #0f172a;
}

.modal-body {
  flex: 1;
  overflow-y: auto;
  padding: 2rem;
}

.item-summary {
  padding-bottom: 1.25rem;
  margin-bottom: 1.5rem;
  border-bottom: 1px solid #e2e8f0;
}

.item-name {
  font-size: 1.125rem;
  font-weight: 700;
  color: #0f172a;
  margin-bottom: 0.375rem;
}

.item-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 1.25rem;
  font-size: 0.875rem;
  color: #64748b;
}

.po-form {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.form-row {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 1rem;
}

.form-field {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.form-field label {
  font-size: 0.813rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #64748b;
}

.form-field input,
.form-field textarea {
  padding: 0.625rem 0.75rem;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 0.938rem;
  font-family: inherit;
  color: #0f172a;
  background: white;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.form-field textarea {
  resize: vertical;
}

.form-field input:focus,
.form-field textarea:focus {
  outline: none;
  border-color: #2563eb;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.15);
}

.form-field input.invalid {
  border-color: #dc2626;
}

.field-error {
  font-size: 0.813rem;
  color: #dc2626;
}

.error-banner {
  padding: 0.75rem 1rem;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 8px;
  color: #991b1b;
  font-size: 0.875rem;
}

.state-message {
  text-align: center;
  padding: 2rem 0;
  color: #64748b;
  font-size: 0.938rem;
}

.info-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 1.5rem;
}

.info-item {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.info-item.full-width {
  grid-column: 1 / -1;
}

.info-label {
  font-size: 0.813rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #64748b;
}

.info-value {
  font-size: 0.938rem;
  color: #0f172a;
  font-weight: 500;
  overflow-wrap: anywhere;
}

.info-value.mono {
  font-family: 'Monaco', 'Courier New', monospace;
  color: #2563eb;
}

.badge {
  display: inline-block;
  padding: 0.25rem 0.75rem;
  border-radius: 6px;
  font-size: 0.813rem;
  font-weight: 600;
  text-transform: capitalize;
}

.badge.success {
  background: #dcfce7;
  color: #166534;
}

.badge.info {
  background: #dbeafe;
  color: #1e40af;
}

.badge.danger {
  background: #fecaca;
  color: #991b1b;
}

.badge.neutral {
  background: #f1f5f9;
  color: #334155;
}

.modal-footer {
  padding: 1.5rem;
  border-top: 1px solid #e2e8f0;
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
}

.btn-secondary,
.btn-primary {
  padding: 0.625rem 1.25rem;
  border-radius: 8px;
  font-weight: 500;
  font-size: 0.875rem;
  cursor: pointer;
  transition: all 0.15s ease;
  font-family: inherit;
}

.btn-secondary {
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  color: #334155;
}

.btn-secondary:hover {
  background: #e2e8f0;
  border-color: #cbd5e1;
}

.btn-primary {
  background: #0f172a;
  border: 1px solid #0f172a;
  color: white;
}

.btn-primary:hover:not(:disabled) {
  background: #1e293b;
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* Modal transition animations */
.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.2s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.modal-enter-active .modal-container,
.modal-leave-active .modal-container {
  transition: transform 0.2s ease;
}

.modal-enter-from .modal-container,
.modal-leave-to .modal-container {
  transform: scale(0.95);
}

@media (max-width: 520px) {
  .form-row,
  .info-grid {
    grid-template-columns: 1fr;
  }
}
</style>
