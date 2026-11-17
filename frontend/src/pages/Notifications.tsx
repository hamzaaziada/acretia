import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, EmptyState, IconBell, PageHeader, SkeletonRows } from '../ds';
import { useOrgEvents } from '../api/hooks';
import { useI18n } from '../i18n';
import { NotificationList, useNotificationActions, useNotifications } from '../app/shell';

export default function Notifications() {
  const { t } = useI18n();
  const nav = useNavigate();
  const [unreadOnly, setUnreadOnly] = useState(false);
  const res = useNotifications(unreadOnly);
  useOrgEvents((e) => {
    if (e.name === 'notification') res.reload();
  });
  const actions = useNotificationActions(res.reload);
  const rows = res.data ?? [];
  return (
    <div className="acr-page">
      <PageHeader
        title={t('nav.notifications')}
        subtitle={t('notif.subtitle')}
        actions={
          <>
            <Button variant="secondary" aria-pressed={unreadOnly} onClick={() => setUnreadOnly((v) => !v)}>
              {unreadOnly ? t('notif.showAll') : t('notif.onlyUnread')}
            </Button>
            <Button variant="secondary" onClick={actions.readAll}>
              {t('notif.readAll')}
            </Button>
          </>
        }
      />
      {res.loading && !res.data ? (
        <SkeletonRows rows={6} label={t('common.loading')} />
      ) : rows.length === 0 ? (
        <EmptyState icon={<IconBell size={22} />} title={unreadOnly ? t('notif.empty.unread') : t('notif.empty.title')} body={t('notif.empty.body')} action={{ label: unreadOnly ? t('notif.showAll') : t('home.title'), onClick: () => (unreadOnly ? setUnreadOnly(false) : nav('/')) }} />
      ) : (
        <div className="acr-panel">
          <NotificationList rows={rows} onOpen={actions.open} />
        </div>
      )}
    </div>
  );
}
