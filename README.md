# 1.1 Ingest Raw Datasets

import os
import glob
import pandas as pd

# Find parquet files attached to the Kaggle notebook
parquet_files = glob.glob('/kaggle/input/**/*.parquet', recursive=True)

print("Parquet files found:")
for f in parquet_files:
    print(f)

# Find the required files automatically
train_path = next(
    f for f in parquet_files
    if os.path.basename(f) == 'train.parquet'
)

test_path = next(
    f for f in parquet_files
    if os.path.basename(f) == 'test.parquet'
)

sample_path = next(
    f for f in parquet_files
    if os.path.basename(f) == 'sample_submission.parquet'
)

# Load datasets
train_df = pd.read_parquet(train_path)
test_df = pd.read_parquet(test_path)
sample_sub = pd.read_parquet(sample_path)

print(f"\nTrain Dataset Shape: {train_df.shape}")
print(f"Test Dataset Shape:  {test_df.shape}")
print(f"Sample Sub Shape:    {sample_sub.shape}")

# Verify target data type
train_df['target'] = train_df['target'].astype(int)

# Check missing values
print(f"\nMissing values in Train: {train_df.isnull().sum().sum()}")
print(f"Missing values in Test:  {test_df.isnull().sum().sum()}")

# Basic column verification
print("\nTrain Columns:", train_df.columns.tolist())
print("Test Columns:", test_df.columns.tolist())
print("Sample Submission Columns:", sample_sub.columns.tolist())
# 1.2 Target Distribution & Telemetry Summary
print("=== TARGET CLASS DISTRIBUTION ===")
counts = train_df['target'].value_counts()
proportions = train_df['target'].value_counts(normalize=True)

target_summary = pd.DataFrame({
    'Count': counts,
    'Percentage': proportions * 100
})
print(target_summary)

print("\n=== NUMERICAL DESCRIPTIVE STATISTICS (TRAIN) ===")
display(train_df.describe().T)
fig, ax = plt.subplots(1, 2, figsize=(15, 5))

# Target class bar plot
ax[0].bar(['Class 0 (Normal)', 'Class 1 (Anomaly)'], counts.values, color=['#2c3e50', '#e74c3c'], edgecolor='black', alpha=0.85)
ax[0].set_title("Class Imbalance: Normal (99.14%) vs Anomaly (0.86%)", fontsize=13, fontweight='bold')
ax[0].set_ylabel("Record Count")
for i, v in enumerate(counts.values):
    ax[0].text(i, v + 25000, f"{v:,} ({v/len(train_df)*100:.2f}%)", ha='center', fontweight='bold')

# Temporal seasonality plot
monthly_anomaly_rate = train_df.groupby(train_df['Date'].dt.to_period('M'))['target'].mean() * 100
monthly_anomaly_rate.plot(ax=ax[1], color='#e67e22', marker='o', linewidth=2.5, markersize=5)
ax[1].set_title("Monthly Anomaly Rate (%) Across 2020-2024 (Seasonality)", fontsize=13, fontweight='bold')
ax[1].set_ylabel("Anomaly Percentage (%)")
ax[1].set_xlabel("Year-Month")
ax[1].grid(True, linestyle='--', alpha=0.6)

plt.tight_layout()
plt.show()
def engineer_features(train_data, test_data):
    """Apply domain mathematical transformations and feature engineering."""
    train_feat = train_data.copy()
    test_feat = test_data.copy()
    
    for df in [train_feat, test_feat]:
        # 1. Reverse exponential scaling
        df['feat_X3_log'] = np.log(df['X3'])
        df['feat_X4_log'] = np.log(df['X4'])
        
        # 2. Decode categorical sensor state
        df['sensor_cat'] = np.round(np.exp(df['X5'])).astype(int)
        
        # 3. Calendar & Temporal features
        df['year'] = df['Date'].dt.year
        df['month'] = df['Date'].dt.month
        df['day'] = df['Date'].dt.day
        df['dayofweek'] = df['Date'].dt.dayofweek
        df['dayofyear'] = df['Date'].dt.dayofyear
        df['is_weekend'] = (df['dayofweek'] >= 5).astype(int)
        df['quarter'] = df['Date'].dt.quarter
        
        # 4. Harmonic cyclical temporal features
        df['sin_month'] = np.sin(2 * np.pi * df['month'] / 12.0)
        df['cos_month'] = np.cos(2 * np.pi * df['month'] / 12.0)
        df['sin_dayofyear'] = np.sin(2 * np.pi * df['dayofyear'] / 365.25)
        df['cos_dayofyear'] = np.cos(2 * np.pi * df['dayofyear'] / 365.25)
        
        # 5. Sensor interactions & ratios
        df['X1_div_X2'] = df['X1'] / (df['X2'] + 1e-7)
        df['X1_mul_X2'] = df['X1'] * df['X2']
        df['log_X3_mul_log_X4'] = df['feat_X3_log'] * df['feat_X4_log']
        df['log_X3_add_log_X4'] = df['feat_X3_log'] + df['feat_X4_log']
        
    # Group deviations from training sensor category baselines
    cat_stats = train_feat.groupby('sensor_cat')[['X1', 'X2']].mean().rename(
        columns={'X1': 'cat_mean_X1', 'X2': 'cat_mean_X2'}
    )
    
    train_feat = train_feat.merge(cat_stats, on='sensor_cat', how='left')
    test_feat = test_feat.merge(cat_stats, on='sensor_cat', how='left')
    
    for df in [train_feat, test_feat]:
        df['diff_X1_cat'] = df['X1'] - df['cat_mean_X1']
        df['diff_X2_cat'] = df['X2'] - df['cat_mean_X2']
        df.drop(columns=['cat_mean_X1', 'cat_mean_X2'], inplace=True)
        
    return train_feat, test_feat

train_proc, test_proc = engineer_features(train_df, test_df)

feature_cols = [
    'X1', 'X2', 'feat_X3_log', 'feat_X4_log', 'sensor_cat',
    'year', 'month', 'day', 'dayofweek', 'dayofyear', 'is_weekend', 'quarter',
    'sin_month', 'cos_month', 'sin_dayofyear', 'cos_dayofyear',
    'X1_div_X2', 'X1_mul_X2', 'log_X3_mul_log_X4', 'log_X3_add_log_X4',
    'diff_X1_cat', 'diff_X2_cat'
]

print(f"Engineered {len(feature_cols)} features successfully.")
print(f"Processed Train Shape: {train_proc.shape}")
print(f"Processed Test Shape:  {test_proc.shape}")
# Correlation Matrix Heatmap
sample_eda = train_proc.sample(100000, random_state=42)
corr_matrix = sample_eda[feature_cols + ['target']].corr()

plt.figure(figsize=(14, 11))
sns.heatmap(corr_matrix, cmap='vlag', vmin=-0.35, vmax=0.35, center=0,
            annot=False, cbar_kws={'label': 'Pearson Correlation'})
plt.title("Correlation Matrix of Engineered Telemetry Features and Anomaly Target", fontsize=14, fontweight='bold')
plt.tight_layout()
plt.show()

# Top features correlated with anomaly target
print("Top 10 Feature Correlations with Anomaly Target:")
display(corr_matrix['target'].abs().sort_values(ascending=False).head(11))
def optimize_threshold(y_true, y_probs):
    """Locate the decision threshold maximizing Class 1 F1-score."""
    thresholds = np.linspace(0.01, 0.95, 95)
    best_t = 0.5
    best_f1 = 0.0
    for t in thresholds:
        preds = (y_probs >= t).astype(int)
        f1 = f1_score(y_true, preds, pos_label=1, zero_division=0)
        if f1 > best_f1:
            best_f1 = f1
            best_t = t
    return best_t, best_f1

def compute_all_metrics(y_true, y_probs, threshold=0.5):
    """Compute per-class precision, recall, F1, and global ROC/PR AUC."""
    preds = (y_probs >= threshold).astype(int)
    return {
        'threshold': threshold,
        'accuracy': accuracy_score(y_true, preds),
        'f1_class_0': f1_score(y_true, preds, pos_label=0, zero_division=0),
        'f1_class_1': f1_score(y_true, preds, pos_label=1, zero_division=0),
        'precision_class_0': precision_score(y_true, preds, pos_label=0, zero_division=0),
        'precision_class_1': precision_score(y_true, preds, pos_label=1, zero_division=0),
        'recall_class_0': recall_score(y_true, preds, pos_label=0, zero_division=0),
        'recall_class_1': recall_score(y_true, preds, pos_label=1, zero_division=0),
        'macro_f1': f1_score(y_true, preds, average='macro', zero_division=0),
        'roc_auc': roc_auc_score(y_true, y_probs) if len(np.unique(y_true)) > 1 else np.nan,
        'pr_auc': average_precision_score(y_true, y_probs) if len(np.unique(y_true)) > 1 else np.nan
    }
    # Prepare Arrays
X = train_proc[feature_cols].values
y = train_proc['target'].values
X_test = test_proc[feature_cols].values

skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
train_idx, val_idx = next(skf.split(X, y))

X_train, y_train = X[train_idx], y[train_idx]
X_val, y_val = X[val_idx], y[val_idx]

# Preprocessing: StandardScaler for distance & linear models
scaler = StandardScaler()
X_train_scaled = scaler.fit_transform(X_train)
X_val_scaled = scaler.transform(X_val)
X_test_scaled = scaler.transform(X_test)

# Scaled subsample for KNN benchmarking
knn_sub_idx = np.random.choice(len(X_train), size=min(50000, len(X_train)), replace=False)
X_train_knn = X_train_scaled[knn_sub_idx]
y_train_knn = y_train[knn_sub_idx]
val_knn_idx = np.random.choice(len(X_val), size=min(10000, len(X_val)), replace=False)
X_val_knn = X_val_scaled[val_knn_idx]
y_val_knn = y_val[val_knn_idx]

# Model definitions
model_zoo = {
    'Logistic Regression': (LogisticRegression(class_weight='balanced', max_iter=1000, random_state=42), 'scaled'),
    'Decision Tree': (DecisionTreeClassifier(class_weight='balanced', max_depth=12, min_samples_leaf=25, random_state=42), 'raw'),
    'Linear SVM (SGD Calibrated)': (SGDClassifier(loss='log_loss', class_weight='balanced', max_iter=1000, random_state=42), 'scaled'),
    'K-Nearest Neighbors (Subsampled)': (KNeighborsClassifier(n_neighbors=7, weights='distance', n_jobs=-1), 'knn'),
    'Random Forest': (RandomForestClassifier(n_estimators=100, max_depth=16, class_weight='balanced', random_state=42, n_jobs=-1), 'raw'),
    'LightGBM': (lgb.LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=63, scale_pos_weight=12.0, subsample=0.8, colsample_bytree=0.8, random_state=42, n_jobs=-1, verbose=-1), 'raw'),
    'XGBoost': (xgb.XGBClassifier(n_estimators=300, learning_rate=0.05, max_depth=6, scale_pos_weight=12.0, subsample=0.8, colsample_bytree=0.8, tree_method='hist', random_state=42, n_jobs=-1, eval_metric='logloss'), 'raw'),
    'CatBoost': (CatBoostClassifier(iterations=300, learning_rate=0.05, depth=6, auto_class_weights='Balanced', random_seed=42, verbose=0, thread_count=-1), 'raw'),
    'Neural Network (MLP)': (MLPClassifier(hidden_layer_sizes=(128, 64, 32), max_iter=25, batch_size=2048, learning_rate_init=0.003, early_stopping=True, n_iter_no_change=5, random_state=42), 'scaled')
}

benchmark_rows = []
model_probs = {}

for name, (clf, dtype) in model_zoo.items():
    print(f"Training {name}...", end=" ")
    t0 = time.time()
    if dtype == 'scaled':
        clf.fit(X_train_scaled, y_train)
        probs = clf.predict_proba(X_val_scaled)[:, 1]
        y_eval = y_val
    elif dtype == 'knn':
        clf.fit(X_train_knn, y_train_knn)
        probs = clf.predict_proba(X_val_knn)[:, 1]
        y_eval = y_val_knn
    else:
        clf.fit(X_train, y_train)
        probs = clf.predict_proba(X_val)[:, 1]
        y_eval = y_val
    dur = time.time() - t0
    
    best_t, _ = optimize_threshold(y_eval, probs)
    metrics = compute_all_metrics(y_eval, probs, threshold=best_t)
    model_probs[name] = (y_eval, probs)
    
    print(f"Done in {dur:.1f}s | Optimal t*={best_t:.2f} | F1(C1): {metrics['f1_class_1']:.4f} | Acc: {metrics['accuracy']:.4f}")
    
    benchmark_rows.append({
        'Model': name,
        'Fit Time (s)': round(dur, 1),
        'Optimal Threshold': round(best_t, 2),
        'Accuracy': round(metrics['accuracy'], 4),
        'Precision (C0)': round(metrics['precision_class_0'], 4),
        'Recall (C0)': round(metrics['recall_class_0'], 4),
        'F1 (C0 Normal)': round(metrics['f1_class_0'], 4),
        'Precision (C1)': round(metrics['precision_class_1'], 4),
        'Recall (C1)': round(metrics['recall_class_1'], 4),
        'F1 (C1 Anomaly)': round(metrics['f1_class_1'], 4),
        'Macro F1': round(metrics['macro_f1'], 4),
        'PR-AUC': round(metrics['pr_auc'], 4),
        'ROC-AUC': round(metrics['roc_auc'], 4)
    })

leaderboard = pd.DataFrame(benchmark_rows).sort_values(by='F1 (C1 Anomaly)', ascending=False).reset_index(drop=True)
# Display Comparison Leaderboard
print("================================ MODEL COMPARISON BENCHMARK LEADERBOARD ================================")
display(leaderboard)

# Visualize Comparison Leaderboard
plt.figure(figsize=(13, 6))
bars = plt.barh(leaderboard['Model'], leaderboard['F1 (C1 Anomaly)'], color='#34495e', edgecolor='black')
plt.gca().invert_yaxis()
plt.title("Model Comparison: Anomaly Class F1-Score After Threshold Calibration", fontsize=14, fontweight='bold')
plt.xlabel("F1-Score (Class 1 Anomaly)")
for bar in bars:
    w = bar.get_width()
    plt.text(w + 0.005, bar.get_y() + bar.get_height()/2, f"{w:.4f}", va='center', fontweight='bold')
plt.tight_layout()
plt.show()
# 3.1 Champion 5-Fold Out-of-Fold Training
oof_predictions = np.zeros(len(train_proc))
test_fold_predictions = []

lgb_ch_params = {
    'n_estimators': 400,
    'learning_rate': 0.04,
    'num_leaves': 63,
    'scale_pos_weight': 10.0,
    'subsample': 0.85,
    'colsample_bytree': 0.85,
    'random_state': 42,
    'n_jobs': -1,
    'verbose': -1
}

for fold, (trn_i, val_i) in enumerate(skf.split(X, y)):
    clf_f = lgb.LGBMClassifier(**lgb_ch_params)
    clf_f.fit(
        X[trn_i], y[trn_i],
        eval_set=[(X[val_i], y[val_i])],
        callbacks=[lgb.early_stopping(30, verbose=False)]
    )
    val_probs = clf_f.predict_proba(X[val_i])[:, 1]
    oof_predictions[val_i] = val_probs
    test_fold_predictions.append(clf_f.predict_proba(X_test)[:, 1])

# Determine global OOF optimal threshold
opt_oof_t, _ = optimize_threshold(y, oof_predictions)
final_metrics = compute_all_metrics(y, oof_predictions, threshold=opt_oof_t)

print("=== FINAL 5-FOLD OUT-OF-FOLD EVALUATION (LIGHTGBM CHAMPION) ===")
print(f"Optimal Decision Threshold:  {opt_oof_t:.2f}")
print(f"Overall Accuracy:            {final_metrics['accuracy']:.4f}")
print(f"Class 0 (Normal) F1:         {final_metrics['f1_class_0']:.4f} (Prec: {final_metrics['precision_class_0']:.4f}, Rec: {final_metrics['recall_class_0']:.4f})")
print(f"Class 1 (Anomaly) F1:        {final_metrics['f1_class_1']:.4f} (Prec: {final_metrics['precision_class_1']:.4f}, Rec: {final_metrics['recall_class_1']:.4f})")
print(f"Macro F1-Score:              {final_metrics['macro_f1']:.4f}")
print(f"Precision-Recall AUC:        {final_metrics['pr_auc']:.4f}")
print(f"ROC-AUC:                     {final_metrics['roc_auc']:.4f}")
# 3.2 Precision-Recall Curve and ROC Curve
fig, ax = plt.subplots(1, 2, figsize=(16, 6))

# PR Curve
prec_pts, rec_pts, _ = precision_recall_curve(y, oof_predictions)
ax[0].plot(rec_pts, prec_pts, color='#2980b9', lw=2.5, label=f"LightGBM OOF (PR-AUC = {final_metrics['pr_auc']:.4f})")
ax[0].scatter([final_metrics['recall_class_1']], [final_metrics['precision_class_1']], color='#e74c3c', s=120, zorder=5,
              label=f"Selected Threshold t*={opt_oof_t:.2f}\n(F1 = {final_metrics['f1_class_1']:.4f})")
ax[0].set_title("Precision-Recall Curve (Champion Model)", fontsize=13, fontweight='bold')
ax[0].set_xlabel("Recall (Anomaly)")
ax[0].set_ylabel("Precision (Anomaly)")
ax[0].legend(loc='lower left')
ax[0].grid(True, linestyle='--', alpha=0.6)

# ROC Curve
fpr_pts, tpr_pts, _ = roc_curve(y, oof_predictions)
ax[1].plot(fpr_pts, tpr_pts, color='#27ae60', lw=2.5, label=f"LightGBM OOF (ROC-AUC = {final_metrics['roc_auc']:.4f})")
ax[1].plot([0, 1], [0, 1], color='gray', linestyle='--', alpha=0.7)
ax[1].set_title("Receiver Operating Characteristic (ROC)", fontsize=13, fontweight='bold')
ax[1].set_xlabel("False Positive Rate")
ax[1].set_ylabel("True Positive Rate")
ax[1].legend(loc='lower right')
ax[1].grid(True, linestyle='--', alpha=0.6)

plt.tight_layout()
plt.show()
# 3.3 Confusion Matrix
discrete_oof_preds = (oof_predictions >= opt_oof_t).astype(int)
cm_raw = confusion_matrix(y, discrete_oof_preds)
cm_pct = cm_raw.astype('float') / cm_raw.sum(axis=1)[:, np.newaxis]

fig, ax = plt.subplots(1, 2, figsize=(14, 5))
sns.heatmap(cm_raw, annot=True, fmt='d', cmap='Blues', cbar=False, ax=ax[0],
            xticklabels=['Pred 0 (Normal)', 'Pred 1 (Anomaly)'],
            yticklabels=['Actual 0 (Normal)', 'Actual 1 (Anomaly)'])
ax[0].set_title("Confusion Matrix (Counts)", fontsize=13, fontweight='bold')

sns.heatmap(cm_pct, annot=True, fmt='.2%', cmap='Blues', cbar=False, ax=ax[1],
            xticklabels=['Pred 0', 'Pred 1'],
            yticklabels=['Actual 0', 'Actual 1'])
ax[1].set_title("Confusion Matrix (Normalized Rates)", fontsize=13, fontweight='bold')
plt.tight_layout()
plt.show()
# Temporal Split
historical_mask = train_proc['year'] <= 2023
holdout_2024_mask = train_proc['year'] == 2024

X_hist, y_hist = X[historical_mask], y[historical_mask]
X_2024, y_2024 = X[holdout_2024_mask], y[holdout_2024_mask]

backtest_model = lgb.LGBMClassifier(**lgb_ch_params)
backtest_model.fit(X_hist, y_hist)
probs_2024 = backtest_model.predict_proba(X_2024)[:, 1]

opt_bt_t, _ = optimize_threshold(y_2024, probs_2024)
bt_metrics = compute_all_metrics(y_2024, probs_2024, threshold=opt_bt_t)

print("=== TEMPORAL BACKTESTING RESULTS (2024 UNSEEN HOLDOUT) ===")
print(f"Historical Training Samples (2020-2023): {len(y_hist):,}")
print(f"Future Testing Samples (2024):            {len(y_2024):,}")
print(f"Optimal Threshold:                       {opt_bt_t:.2f}")
print(f"2024 Holdout Accuracy:                   {bt_metrics['accuracy']:.4f}")
print(f"2024 Anomaly F1-Score:                   {bt_metrics['f1_class_1']:.4f} (Prec: {bt_metrics['precision_class_1']:.4f}, Rec: {bt_metrics['recall_class_1']:.4f})")
print(f"2024 Normal F1-Score:                    {bt_metrics['f1_class_0']:.4f}")
print(f"2024 PR-AUC:                             {bt_metrics['pr_auc']:.4f}")
print(f"2024 ROC-AUC:                            {bt_metrics['roc_auc']:.4f}")
train_proc['error_class'] = 'TN'
train_proc.loc[(train_proc['target'] == 0) & (discrete_oof_preds == 1), 'error_class'] = 'False Positive'
train_proc.loc[(train_proc['target'] == 1) & (discrete_oof_preds == 0), 'error_class'] = 'False Negative'
train_proc.loc[(train_proc['target'] == 1) & (discrete_oof_preds == 1), 'error_class'] = 'True Positive'
train_proc.loc[(train_proc['target'] == 0) & (discrete_oof_preds == 0), 'error_class'] = 'True Negative'

print("Error Category Summary (Mean Feature Values):")
display(train_proc.groupby('error_class')[['X1', 'X2', 'feat_X3_log', 'feat_X4_log', 'sensor_cat']].mean().round(3))

fig, axes = plt.subplots(1, 2, figsize=(15, 5))
sns.boxplot(data=train_proc, x='error_class', y='X1', ax=axes[0], palette='Set2', showfliers=False)
axes[0].set_title("X1 Distribution Across Prediction Categories", fontweight='bold')
sns.boxplot(data=train_proc, x='error_class', y='X2', ax=axes[1], palette='Set2', showfliers=False)
axes[1].set_title("X2 Distribution Across Prediction Categories", fontweight='bold')
plt.tight_layout()
plt.show()
# 3.4 Feature Importance Analysis
feat_imp_df = pd.DataFrame({
    'Feature': feature_cols,
    'Importance': clf_f.feature_importances_
}).sort_values('Importance', ascending=False)

plt.figure(figsize=(11, 7))
sns.barplot(data=feat_imp_df.head(15), x='Importance', y='Feature', palette='mako')
plt.title("Top 15 Feature Importances (Champion LightGBM)", fontsize=14, fontweight='bold')
plt.xlabel("Split Feature Importance")
plt.tight_layout()
plt.show()
# Aggregate ensemble test probabilities
ensemble_test_probs = np.mean(test_fold_predictions, axis=0)
ensemble_test_preds = (ensemble_test_probs >= opt_oof_t).astype(int)

# Create submission dataframe
submission = pd.DataFrame({
    'ID': test_proc['ID'].astype('int64'),
    'target': ensemble_test_preds.astype(str)
})

# Export to parquet and csv
submission.to_parquet('submission.parquet', index=False)
submission.to_csv('submission.csv', index=False)

print("=== SUBMISSION VERIFICATION ===")
print(f"File created: submission.parquet (Shape: {submission.shape})")
print(f"File created: submission.csv     (Shape: {submission.shape})")
print(f"Columns: {submission.columns.tolist()}")
print(f"Data types:\n{submission.dtypes}")
print("\nFirst 10 submission rows:")
display(submission.head(10))

print("\nTest Set Class Distribution:")
display(submission['target'].value_counts())
display(submission['target'].value_counts(normalize=True) * 100)
