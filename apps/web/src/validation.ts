export interface DemoPreferences {
  residenceName: string
  startDay: string
}

export type DemoPreferencesErrors = Partial<Record<keyof DemoPreferences, string>>

export function validateDemoPreferences(values: DemoPreferences): DemoPreferencesErrors {
  const errors: DemoPreferencesErrors = {}
  const normalizedName = values.residenceName.trim()

  if (normalizedName.length === 0) {
    errors.residenceName = 'Informe um nome para identificar a residência.'
  } else if (normalizedName.length < 3) {
    errors.residenceName = 'Use pelo menos 3 caracteres.'
  } else if (normalizedName.length > 60) {
    errors.residenceName = 'Use no máximo 60 caracteres.'
  }

  const startDay = Number(values.startDay)
  if (!Number.isInteger(startDay) || startDay < 1 || startDay > 28) {
    errors.startDay = 'Escolha um dia entre 1 e 28.'
  }

  return errors
}

export function hasValidationErrors(errors: DemoPreferencesErrors): boolean {
  return Object.keys(errors).length > 0
}
