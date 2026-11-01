const original = require('./app.json').expo;

module.exports = () => {
  if (process.env.PLAYAURAL_MARCO_BUILD !== '1') return original;
  const { eas, ...extra } = original.extra || {};
  return {
    ...original,
    name: 'PlayAural Marco',
    slug: 'playaural-marco',
    android: {
      ...original.android,
      package: 'com.marcoml.playaural',
      versionCode: Number(process.env.PLAYAURAL_ANDROID_VERSION_CODE || '10503001'),
    },
    ios: { ...original.ios, bundleIdentifier: 'com.marcoml.playaural' },
    extra,
  };
};
