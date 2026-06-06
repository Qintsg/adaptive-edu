import type { GlobalThemeOverrides } from 'naive-ui'
import { fluentTokens } from './fluent-tokens'

const { color, radius, shadow, font } = fluentTokens

export const naiveThemeOverrides: GlobalThemeOverrides = {
  common: {
    fontFamily: font.family,
    fontSize: font.sizeBase,
    primaryColor: color.brand,
    primaryColorHover: color.brandHover,
    primaryColorPressed: color.brandPressed,
    primaryColorSuppl: color.brandHover,
    successColor: color.success,
    warningColor: color.warning,
    errorColor: color.danger,
    infoColor: color.info,
    textColorBase: color.textPrimary,
    textColor1: color.textPrimary,
    textColor2: color.textSecondary,
    textColor3: color.textTertiary,
    borderColor: color.border,
    borderRadius: radius.medium,
    borderRadiusSmall: radius.small,
    boxShadow1: shadow.light,
    boxShadow2: shadow.medium,
    boxShadow3: shadow.heavy
  },
  Button: {
    borderRadiusMedium: radius.medium,
    borderRadiusLarge: radius.large,
    fontWeight: '600',
    paddingMedium: '0 16px'
  },
  Card: {
    borderRadius: radius.large,
    boxShadow: shadow.light,
    paddingMedium: '20px',
    paddingLarge: '24px'
  },
  Dialog: {
    borderRadius: radius.large
  },
  Drawer: {
    borderRadius: radius.large
  },
  Input: {
    borderRadius: radius.medium
  },
  Menu: {
    itemBorderRadius: radius.medium,
    itemTextColorActive: color.brand,
    itemIconColorActive: color.brand,
    itemColorActive: color.brandSubtle,
    itemColorActiveHover: color.brandSubtle
  },
  Modal: {
    borderRadius: radius.large
  },
  Select: {
    borderRadius: radius.medium
  },
  Tag: {
    borderRadius: radius.round
  }
}
