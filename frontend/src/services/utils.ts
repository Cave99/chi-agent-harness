import classNames from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: (string | undefined | null | false)[]) {
  return twMerge(classNames(inputs));
}

export const TYPE_DISPLAY: Record<string, string> = {
  numerical:    'int',
  categorical:  'str',
  boolean:      'bool',
  freeform_text:'text',
  date:         'date',
};

export const TYPE_COLOUR: Record<string, string> = {
  numerical:    'text-blue-600',
  categorical:  'text-violet-600',
  boolean:      'text-emerald-600',
  freeform_text:'text-amber-600',
  date:         'text-sky-600',
};
